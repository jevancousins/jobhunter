#!/usr/bin/env python3
"""Open an application folder in Finder and the job URL in the browser.

Usage:
    python scripts/open_application.py <role-id>
    python scripts/open_application.py <linkedin-job-url>
    python scripts/open_application.py <notion-page-url>

The script:
  1. Resolves the application folder from the given ID or URL
  2. Prints MANUAL-APPLY.md to the terminal (if it exists)
  3. Opens the application folder in Finder
  4. Opens the job URL in your default browser
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APPLICATIONS_DIR = ROOT / "applications"

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))


def _extract_id(raw: str) -> str:
    """Best-effort extraction of a LinkedIn job ID from various input forms."""
    s = raw.strip().rstrip("/")
    # Notion page URL: ends in 32-char hex or UUID-with-title
    # Just use the last path segment stripped of query params as a candidate
    last = s.split("?")[0].split("/")[-1]
    # LinkedIn job view URL
    if "linkedin.com/jobs/view/" in s:
        return s.split("linkedin.com/jobs/view/")[-1].split("?")[0].split("/")[0]
    # Pure numeric ID
    if last.isdigit():
        return last
    # LinkedIn short numeric at end of path
    parts = s.split("/")
    for part in reversed(parts):
        clean = part.split("?")[0]
        if clean.isdigit():
            return clean
    return last


def _find_role_dir(query: str) -> Path | None:
    """Resolve an application folder from a job ID, URL, or company/title keyword."""
    # Direct folder match (numeric LinkedIn job ID)
    candidate = APPLICATIONS_DIR / query
    if candidate.exists():
        return candidate

    # Collect all role-context.json files once for any fuzzy search
    candidates = []
    for d in APPLICATIONS_DIR.iterdir():
        if not d.is_dir():
            continue
        rc = d / "role-context.json"
        if not rc.exists():
            continue
        try:
            data = json.loads(rc.read_text())
        except Exception:
            continue
        # URL / Notion page ID match
        if query in (data.get("url") or "") or query in (data.get("notion_page_id") or ""):
            return d
        candidates.append((d, data))

    # Keyword search: company or title substring (case-insensitive)
    q = query.lower()
    matches = [
        (d, data) for d, data in candidates
        if q in (data.get("company") or "").lower() or q in (data.get("title") or "").lower()
    ]
    if len(matches) == 1:
        return matches[0][0]
    if len(matches) > 1:
        # Prefer Escalated status if available, otherwise return all and let user pick
        print(f"Multiple matches for {query!r}:")
        for i, (d, data) in enumerate(matches):
            print(f"  [{i}] {data.get('title','?')} @ {data.get('company','?')}  ({d.name})")
        try:
            choice = int(input("Pick number: "))
            return matches[choice][0]
        except (ValueError, IndexError, EOFError):
            return matches[0][0]
    return None


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python scripts/open_application.py <role-id-or-url>")
        return 1

    raw = sys.argv[1]
    # Try direct job ID extraction first for numeric / LinkedIn URL inputs
    rid = _extract_id(raw)
    role_dir = _find_role_dir(rid)
    # Fall back to keyword search if direct ID lookup failed
    if not role_dir and not rid.isdigit():
        role_dir = _find_role_dir(raw)

    if not role_dir:
        print(f"No application folder found for: {raw!r}")
        print("Try a LinkedIn job ID, job URL, or company/title keyword.")
        return 1

    rc_path = role_dir / "role-context.json"
    rc = json.loads(rc_path.read_text()) if rc_path.exists() else {}
    title = rc.get("title", rid)
    company = rc.get("company", "")
    url = rc.get("url", f"https://www.linkedin.com/jobs/view/{rid}")

    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"  {company}")
    print(f"  {url}")
    print(f"{'='*60}\n")

    manual = role_dir / "MANUAL-APPLY.md"
    if manual.exists():
        print(manual.read_text())
    else:
        print("(No MANUAL-APPLY.md found; run mark-escalated to generate one.)\n")
        # Show CV filename at least. The employer-facing filename prefix comes
        # from search_config.json cv.employer_filename_base.
        cv_glob = "*.pdf"
        try:
            from user_config import load_search_config
            base = load_search_config().get("cv", {}).get("employer_filename_base", "")
            if base:
                cv_glob = f"{base}*.pdf"
        except SystemExit:
            pass  # config missing; fall back to listing every PDF
        for pdf in role_dir.glob(cv_glob):
            print(f"CV: {pdf.name}")

    # Open folder in Finder and URL in browser
    subprocess.run(["open", str(role_dir)])
    subprocess.run(["open", url])

    return 0


if __name__ == "__main__":
    sys.exit(main())
