#!/usr/bin/env python3
"""
One-time setup: log into LinkedIn and persist auth so the auto-apply skill
can drive LinkedIn as you, in the background, in later runs.

Uses the Python Playwright API directly (not the playwright-cli subprocess
flow, which is brittle for OAuth-style logins like LinkedIn's Google SSO).
A persistent user-data-dir at data/.playwright-profile/ keeps the browser
profile alive across runs, so Google treats subsequent logins as a returning
device and doesn't re-prompt 2FA every time.

The script ALSO exports a portable storage-state JSON to
data/.linkedin-state.json, which is what the auto-apply skill loads via
playwright-cli state-load.

Run this once after installing playwright. Run it again whenever LinkedIn
forces a re-auth (typically every 2-3 months, sooner if you change password
or sign out elsewhere).

Usage:
    python scripts/save_linkedin_state.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

REPO_ROOT = Path(__file__).resolve().parent.parent
PROFILE_DIR = REPO_ROOT / "data" / ".playwright-profile"
STATE_FILE = REPO_ROOT / "data" / ".linkedin-state.json"

LOGIN_URL = "https://www.linkedin.com/login"


def has_auth_cookie(context) -> bool:
    """Return True iff the LinkedIn session cookie (li_at) is present."""
    cookies = context.cookies()
    return any(
        c.get("name") == "li_at" and "linkedin.com" in c.get("domain", "")
        for c in cookies
    )


def main() -> int:
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        print("Launching Chromium...")
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
            viewport={"width": 1280, "height": 900},
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(LOGIN_URL)

        print()
        print("=" * 60)
        print("LOG IN to LinkedIn in the browser window that just opened.")
        print("Use whatever method you prefer (email + password or Google SSO).")
        print("Complete any 2FA or captcha that LinkedIn or Google show you.")
        print("Once you can see your LinkedIn home feed, come back here.")
        print("=" * 60)
        print()

        attempt = 0
        while True:
            attempt += 1
            try:
                input("Press Enter once you're logged in (or Ctrl-C to abort): ")
            except KeyboardInterrupt:
                print("\nAborted by user.")
                context.close()
                return 130

            if has_auth_cookie(context):
                break

            print()
            print("No li_at cookie yet (that's the LinkedIn session token).")
            print("Either you're not fully logged in, or a 2FA / captcha step is")
            print("still pending in the browser. Complete it and try Enter again.")
            if attempt >= 5:
                print()
                print("Five attempts and still no auth cookie. Aborting so we can")
                print("debug. Leave the browser open and check the developer console")
                print("for any obvious errors before re-running.")
                context.close()
                return 1
            print()

        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        context.storage_state(path=str(STATE_FILE))

        size_kb = STATE_FILE.stat().st_size / 1024
        print()
        print(f"LinkedIn state saved: {STATE_FILE} ({size_kb:.1f} KB)")
        print(f"Persistent profile:   {PROFILE_DIR}")
        print("Refresh quarterly or after any forced re-auth.")

        context.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
