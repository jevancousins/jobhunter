"""Sweep Failed/Escalated roles for LinkedIn expiry markers, mark as Expired.

For every Notion row with Status in (Failed, Escalated) and a
linkedin.com/jobs/view/ URL, opens the LinkedIn page in the shared
auto-apply playwright session, looks for the "no longer accepting
applications" marker text, and sets Status=Expired if found.

We deliberately do NOT follow apply links to external ATSes — only the
LinkedIn page itself is inspected, per user request.

Usage:
    python scripts/sweep_expired.py            # process all Failed+Escalated
    python scripts/sweep_expired.py --limit 50 # cap roles processed
    python scripts/sweep_expired.py --dry-run  # report, do not change Notion
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from auto_apply import (  # noqa: E402  pylint: disable=wrong-import-position
    SESSION_NAME,
    pcli,
    pcli_eval,
    notion_run,
    STATUS_EXPIRED,
)

EXPIRY_PATTERN = re.compile(
    r"no longer accepting applications"
    r"|applications are no longer being accepted"
    r"|this job is no longer",
    re.IGNORECASE,
)

LINKEDIN_VIEW = "linkedin.com/jobs/view/"


def fetch_rows(status: str) -> list[dict]:
    out = subprocess.check_output(
        [sys.executable, str(ROOT / "scripts" / "auto_apply.py"),
         "list-queue", "--status", status]
    )
    return json.loads(out)


def is_expired(url: str, timeout: int = 20) -> tuple[bool, str]:
    """Return (expired, snippet). snippet is a 120-char excerpt if matched."""
    try:
        pcli("goto", url, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    except Exception as e:  # noqa: BLE001
        return False, f"GOTO_ERROR: {e}"
    time.sleep(1.0)
    try:
        text = pcli_eval(
            "(() => (document.body.innerText || '').slice(0, 4000))()"
        )
    except Exception as e:  # noqa: BLE001
        return False, f"EVAL_ERROR: {e}"
    if not isinstance(text, str):
        return False, "NO_TEXT"
    m = EXPIRY_PATTERN.search(text)
    if not m:
        return False, ""
    start = max(0, m.start() - 30)
    end = min(len(text), m.end() + 30)
    return True, text[start:end].replace("\n", " ").strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None,
                    help="Cap number of roles processed.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Do not update Notion; just report findings.")
    ap.add_argument("--statuses", default="Failed,Escalated",
                    help="Comma-separated Notion statuses to sweep.")
    args = ap.parse_args()

    rows: list[dict] = []
    for status in args.statuses.split(","):
        status = status.strip()
        if not status:
            continue
        s_rows = fetch_rows(status)
        for r in s_rows:
            r["_origin_status"] = status
            rows.append(r)

    # Keep only LinkedIn URLs; dedupe by id.
    seen: set[str] = set()
    targets: list[dict] = []
    for r in rows:
        rid = r.get("id") or ""
        url = r.get("url") or ""
        if rid in seen or LINKEDIN_VIEW not in url:
            continue
        seen.add(rid)
        targets.append(r)

    if args.limit:
        targets = targets[: args.limit]

    print(f"Sweeping {len(targets)} LinkedIn roles "
          f"(across statuses: {args.statuses}, dry_run={args.dry_run}).")

    # Ensure session is open + authenticated (idempotent — session-open is a no-op
    # if the named session already exists).
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "auto_apply.py"), "session-open"],
        check=True,
    )

    n_expired = 0
    n_alive = 0
    n_error = 0
    log_path = ROOT / "data" / f"sweep-expired-{int(time.time())}.jsonl"
    with log_path.open("w") as logf:
        for i, r in enumerate(targets, 1):
            rid = r["id"]
            url = r["url"]
            page_id = r.get("page_id") or ""
            expired, snippet = is_expired(url)
            entry = {
                "id": rid, "title": r.get("title"),
                "company": r.get("company"),
                "origin_status": r.get("_origin_status"),
                "url": url, "page_id": page_id,
                "expired": expired, "snippet": snippet,
            }

            if snippet.startswith(("TIMEOUT", "GOTO_ERROR", "EVAL_ERROR", "NO_TEXT")):
                n_error += 1
                tag = f"ERR  ({snippet[:30]})"
            elif expired:
                n_expired += 1
                tag = "EXP"
                if not args.dry_run and page_id:
                    notion_run("update-status", page_id, STATUS_EXPIRED)
            else:
                n_alive += 1
                tag = "ok "

            logf.write(json.dumps(entry) + "\n")
            print(f"  [{i:4d}/{len(targets)}]  {tag}  {rid}  "
                  f"{(r.get('company') or '')[:24]:24s}  "
                  f"{(r.get('title') or '')[:50]}", flush=True)

    # Leave the session open; caller decides whether to close.
    print()
    print(f"Sweep complete. Expired: {n_expired}  Alive: {n_alive}  Errors: {n_error}.")
    print(f"Log: {log_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
