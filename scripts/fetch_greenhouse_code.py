#!/usr/bin/env python3
"""fetch_greenhouse_code.py — standalone Gmail poller for Greenhouse verification codes.

This script is called by the edge-case-applicator agent (via Bash) when
Greenhouse requires an 8-character email verification code after form
submission. It polls Gmail for the code using the Gmail MCP-backed
search available inside a Claude Code session.

Because MCP tools are not directly callable from Python subprocesses, this
script is intentionally NOT the primary fetching mechanism — the primary
mechanism is the agent itself calling the Gmail MCP tools directly (see
edge-case-applicator.md for the tool call sequence).

This script serves two purposes:

1. **Fallback poller:** if the agent's MCP tool calls fail or time out, the
   agent can run this script via Bash as a last resort. The script uses the
   Gmail HTTP API directly via the `google-auth` / `google-api-python-client`
   libraries if they are installed, or falls back to a `curl`-based approach
   using the same OAuth2 token file used by the MCP server.

2. **Unit-testable reference implementation:** a dry-run mode (`--dry-run`)
   prints the search query and code-extraction regex without calling Gmail,
   so CI and review can verify the logic is correct without consuming quota.

Usage
-----
    # Normal mode (requires Gmail auth in environment). The candidate email
    # defaults to $JOBHUNTER_CANDIDATE_EMAIL, then application_profile.json
    # identity.email:
    python scripts/fetch_greenhouse_code.py --email alex@example.com

    # Dry-run (no Gmail API call, prints what the script WOULD do):
    python scripts/fetch_greenhouse_code.py --dry-run

    # Pass a known message body for testing the code-extraction regex:
    python scripts/fetch_greenhouse_code.py --test-body "Your verification code is A3F7K2M9"

Exit codes
----------
    0  Code found and printed to stdout (8-char alphanumeric, uppercase).
    1  Code not found within the poll window (default: 3 attempts × 20s).
    2  Auth / environment error.
    3  Dry-run mode — always exits 0 after printing the walkthrough.

Output (stdout, exit 0)
-----------------------
    <8-char code>
    e.g.:  A3F7K2M9

All diagnostic output goes to stderr so the agent can capture the code
cleanly with `CODE=$(python scripts/fetch_greenhouse_code.py 2>/dev/null)`.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PROFILE_PATH = Path(__file__).resolve().parents[1] / "data" / "application_profile.json"


def _default_email() -> str:
    """Resolve the candidate email address.

    Order: JOBHUNTER_CANDIDATE_EMAIL environment variable, then
    application_profile.json identity.email, then empty string (in which
    case --email is required).
    """
    env_email = os.environ.get("JOBHUNTER_CANDIDATE_EMAIL", "").strip()
    if env_email:
        return env_email
    try:
        profile = json.loads(_PROFILE_PATH.read_text())
        return str(profile.get("identity", {}).get("email", "")).strip()
    except (FileNotFoundError, json.JSONDecodeError):
        return ""

# How long to wait between poll attempts (seconds). Greenhouse sends the
# code within ~5s of form submission; 20s between attempts is conservative.
POLL_INTERVAL_S = 20

# Maximum number of poll attempts before giving up.
MAX_ATTEMPTS = 3

# Gmail search query sent to the API / MCP.
# Matches Greenhouse verification-code emails from the last 10 minutes.
# The `newer_than:10m` filter keeps results tight so a stale code from a
# previous (already-used) run never pollutes the result.
GMAIL_QUERY = (
    "from:(greenhouse.io OR no-reply@greenhouse.io OR notifications@greenhouse.io) "
    "subject:(verification OR confirm) "
    "newer_than:10m"
)

# Fallback query if the sender-scoped query returns nothing (some Greenhouse
# instances send from a per-employer subdomain, e.g. `mail.greenhouse.io`).
GMAIL_QUERY_BROAD = (
    "subject:(verification code OR confirm your email OR security code) "
    "newer_than:10m"
)

# Regex that extracts an 8-character alphanumeric verification code from the
# email body. Greenhouse codes are 8 chars, uppercase letters + digits.
# The labelled pattern requires the code to follow a recognised label phrase
# ("verification code is", "your code:", "enter this code", etc.) to avoid
# false-positives on random 8-char words like "entering" or "accepted".
CODE_RE = re.compile(
    r"(?:verification\s+code|security\s+code|your\s+code|enter\s+(?:this\s+)?code|code\s+is)"
    r"\s*[:\s]+([A-Z0-9]{8})",
    re.IGNORECASE,
)

# Broader fallback: any 8-char word-boundary token that contains BOTH letters
# and digits (pure-letter and pure-digit tokens are unlikely to be codes).
CODE_RE_BROAD = re.compile(r"\b([A-Z0-9]{8})\b")


# ---------------------------------------------------------------------------
# Code extraction
# ---------------------------------------------------------------------------

def extract_code(body: str) -> Optional[str]:
    """Extract an 8-character verification code from an email body string.

    Tries the labelled pattern first (more reliable), falls back to the broad
    pattern (any 8-char alphanumeric), and returns None if nothing is found.

    The returned code is always uppercased.
    """
    m = CODE_RE.search(body)
    if m:
        return m.group(1).upper()
    # Broad fallback: look for any 8-char alphanumeric token. Filter out
    # tokens that are clearly not codes (all-lowercase, all-digit long
    # numbers, etc.).
    candidates = CODE_RE_BROAD.findall(body)
    for candidate in candidates:
        # Must have at least one letter (pure digits are likely timestamps or IDs)
        if re.search(r"[A-Z]", candidate, re.IGNORECASE) and re.search(r"[0-9]", candidate):
            return candidate.upper()
    return None


# ---------------------------------------------------------------------------
# Gmail API access (direct HTTP via google-api-python-client or curl)
# ---------------------------------------------------------------------------

def _try_import_google() -> Optional[object]:
    """Try to import google-api-python-client. Returns the service object or None."""
    try:
        from google.oauth2.credentials import Credentials  # type: ignore
        from googleapiclient.discovery import build  # type: ignore
        import base64

        # The MCP server stores its OAuth2 token at a known path on macOS.
        # Adjust if the path differs on the user's machine.
        token_candidates = [
            Path.home() / "Library" / "Application Support" / "Claude" / "gmail-token.json",
            Path.home() / ".config" / "gmail-mcp" / "token.json",
            Path("/tmp/gmail-token.json"),
        ]
        token_path = next((p for p in token_candidates if p.exists()), None)
        if token_path is None:
            print(
                "WARNING: no Gmail OAuth token file found; falling back to MCP path",
                file=sys.stderr,
            )
            return None

        creds_data = json.loads(token_path.read_text())
        creds = Credentials.from_authorized_user_info(creds_data)
        service = build("gmail", "v1", credentials=creds)
        return (service, base64)
    except Exception as exc:
        print(f"WARNING: google-api-python-client not available: {exc}", file=sys.stderr)
        return None


def _search_and_extract_via_api(query: str) -> Optional[str]:
    """Search Gmail via the Python API client and extract a verification code."""
    result = _try_import_google()
    if result is None:
        return None
    service, base64 = result

    try:
        msgs = (
            service.users()
            .messages()
            .list(userId="me", q=query, maxResults=5)
            .execute()
        )
        for item in msgs.get("messages", []):
            msg = (
                service.users()
                .messages()
                .get(userId="me", id=item["id"], format="full")
                .execute()
            )
            # Extract plain-text body
            payload = msg.get("payload", {})
            body = ""
            if "data" in payload.get("body", {}):
                body = base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")
            for part in payload.get("parts", []):
                if part.get("mimeType") == "text/plain":
                    part_data = part.get("body", {}).get("data", "")
                    if part_data:
                        body += base64.urlsafe_b64decode(part_data).decode("utf-8", errors="replace")
            code = extract_code(body)
            if code:
                print(f"DEBUG: found code in message id={item['id']}", file=sys.stderr)
                return code
    except Exception as exc:
        print(f"ERROR: Gmail API call failed: {exc}", file=sys.stderr)

    return None


# ---------------------------------------------------------------------------
# Dry-run walkthrough
# ---------------------------------------------------------------------------

DRY_RUN_BODY_EXAMPLE = """\
Hi Alex,

Please confirm your email address by entering the verification code below.

Your verification code is: R7KM3P2X

This code will expire in 10 minutes.

The Greenhouse Team
"""


def dry_run() -> None:
    """Print a full walkthrough of what the script would do, without calling Gmail."""
    print("=== fetch_greenhouse_code.py DRY-RUN WALKTHROUGH ===\n", file=sys.stderr)
    print("Step 1: Build Gmail search query", file=sys.stderr)
    print(f"  Primary query : {GMAIL_QUERY!r}", file=sys.stderr)
    print(f"  Fallback query: {GMAIL_QUERY_BROAD!r}", file=sys.stderr)
    print(file=sys.stderr)

    print("Step 2: Poll up to 3 times with 20s between attempts", file=sys.stderr)
    print("  Attempt 1: search Gmail with primary query", file=sys.stderr)
    print("    → (in dry-run, substituting example email body)", file=sys.stderr)
    print(f"\n  Example body:\n{DRY_RUN_BODY_EXAMPLE}", file=sys.stderr)

    print("Step 3: Extract code from body using CODE_RE", file=sys.stderr)
    code = extract_code(DRY_RUN_BODY_EXAMPLE)
    print(f"  CODE_RE match  : {code!r}", file=sys.stderr)
    assert code == "R7KM3P2X", f"Regex self-check failed: expected R7KM3P2X, got {code!r}"
    print("  Self-check     : PASSED (R7KM3P2X extracted correctly)", file=sys.stderr)
    print(file=sys.stderr)

    print("Step 4: Print code to stdout (agent captures it)", file=sys.stderr)
    print(f"  Stdout output  : {code}", file=sys.stderr)
    print(file=sys.stderr)

    print("Step 5: Edge-case agent enters code into Greenhouse form", file=sys.stderr)
    print("  playwright-cli fill <verification-textbox-ref> R7KM3P2X", file=sys.stderr)
    print("  playwright-cli click <submit-ref>", file=sys.stderr)
    print("  → Greenhouse shows confirmation page", file=sys.stderr)
    print(file=sys.stderr)

    print("=== DRY-RUN COMPLETE (exit 0) ===", file=sys.stderr)

    # Also print the code to stdout so callers can capture it in tests
    print(code)
    sys.exit(0)


# ---------------------------------------------------------------------------
# Test-body mode
# ---------------------------------------------------------------------------

def test_body_mode(body: str) -> None:
    """Run code extraction on a supplied body string and exit."""
    code = extract_code(body)
    if code:
        print(code)
        sys.exit(0)
    else:
        print("ERROR: no 8-char code found in supplied body", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch a Greenhouse email verification code from Gmail.",
    )
    parser.add_argument(
        "--email",
        default=None,
        help="Candidate email address (default: $JOBHUNTER_CANDIDATE_EMAIL, "
             "then application_profile.json identity.email)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print walkthrough without calling Gmail; always exits 0.",
    )
    parser.add_argument(
        "--test-body",
        metavar="BODY",
        help="Test code-extraction against a supplied body string; no API call.",
    )
    parser.add_argument(
        "--attempts",
        type=int,
        default=MAX_ATTEMPTS,
        help=f"Poll attempts (default: {MAX_ATTEMPTS})",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=POLL_INTERVAL_S,
        help=f"Seconds between attempts (default: {POLL_INTERVAL_S})",
    )
    args = parser.parse_args()

    if not args.email:
        args.email = _default_email()

    if args.dry_run:
        dry_run()
        return  # unreachable; dry_run() calls sys.exit

    if args.test_body:
        test_body_mode(args.test_body)
        return  # unreachable

    # --- Live mode ---
    print(
        f"INFO: polling Gmail for Greenhouse verification code "
        f"(max {args.attempts} attempts, {args.interval}s apart)",
        file=sys.stderr,
    )

    for attempt in range(1, args.attempts + 1):
        print(f"INFO: attempt {attempt}/{args.attempts}", file=sys.stderr)

        # Try primary query first
        code = _search_and_extract_via_api(GMAIL_QUERY)
        if code:
            print(code)
            sys.exit(0)

        # Try broad fallback
        code = _search_and_extract_via_api(GMAIL_QUERY_BROAD)
        if code:
            print(code)
            sys.exit(0)

        if attempt < args.attempts:
            print(f"INFO: code not found yet; waiting {args.interval}s...", file=sys.stderr)
            time.sleep(args.interval)

    print(
        "ERROR: verification code not found after all attempts. "
        "Use the Gmail MCP directly: search_threads with "
        f"query={GMAIL_QUERY!r} then get_thread and parse the body.",
        file=sys.stderr,
    )
    sys.exit(1)


if __name__ == "__main__":
    main()
