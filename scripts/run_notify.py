#!/usr/bin/env python3
"""Send a desktop notification (macOS) and (optionally) an email summary.

Used by the auto-apply daily script and the watchdog to surface run outcomes.
Standard library only, so it runs reliably from a launchd/cron context with no
venv.

Behaviour is driven by the `notifications` block of data/search_config.json
(created from data/search_config.example.json by /onboard):
  - notifications.email: recipient (and sender) address. Empty disables email.
  - notifications.smtp_host: SMTP server (default smtp.gmail.com).
  - notifications.desktop_notifications: enable macOS desktop notifications.

Email authenticates with an SMTP *app password* (for Gmail, not your normal
password). Provide it via either:
  - the file  ~/.config/jobhunter/gmail_app_password   (recommended), or
  - the environment variable  GMAIL_APP_PASSWORD

If no app password is found, the email is skipped gracefully and the desktop
notification still fires. Create a Gmail app password at:
  https://myaccount.google.com/apppasswords
"""
import argparse
import os
import ssl
import smtplib
import subprocess
import sys
from email.message import EmailMessage
from pathlib import Path

APP_PW_FILE = Path.home() / ".config" / "jobhunter" / "gmail_app_password"

DEFAULT_SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587


def _notifications_config() -> dict:
    """Return the notifications block of data/search_config.json, or {}.

    Missing or invalid config must never break a notification call from a
    headless run, so every failure mode degrades to an empty dict (which
    disables email and desktop notifications).
    """
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from user_config import load_search_config

        return load_search_config().get("notifications", {}) or {}
    except SystemExit:
        # user_config exits with guidance when data/search_config.json is
        # missing; a notifier should stay quiet instead.
        return {}
    except Exception as e:  # noqa: BLE001
        print(f"[run_notify] could not load notifications config: {e}", file=sys.stderr)
        return {}


def desktop(title: str, message: str, subtitle: str | None = None, sound: str | None = "Glass") -> None:
    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace('"', '\\"')

    script = f'display notification "{esc(message)}" with title "{esc(title)}"'
    if subtitle:
        script += f' subtitle "{esc(subtitle)}"'
    if sound:
        script += f' sound name "{esc(sound)}"'
    try:
        subprocess.run(["osascript", "-e", script], check=False, timeout=15)
    except Exception as e:  # noqa: BLE001
        print(f"[run_notify] desktop notification failed: {e}", file=sys.stderr)


def _app_password() -> str | None:
    pw = os.environ.get("GMAIL_APP_PASSWORD")
    if pw:
        return pw.strip()
    if APP_PW_FILE.exists():
        return APP_PW_FILE.read_text().strip()
    return None


def email(subject: str, body: str, address: str, smtp_host: str) -> bool:
    if not address:
        print(
            "[run_notify] email skipped: notifications.email is empty in "
            "data/search_config.json",
            file=sys.stderr,
        )
        return False
    pw = _app_password()
    if not pw:
        print(
            f"[run_notify] email skipped: no app password at {APP_PW_FILE} "
            "or $GMAIL_APP_PASSWORD",
            file=sys.stderr,
        )
        return False
    pw = pw.replace(" ", "")  # Google displays app passwords in groups of 4
    msg = EmailMessage()
    msg["From"] = address
    msg["To"] = address
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP(smtp_host, SMTP_PORT, timeout=30) as s:
            s.starttls(context=ctx)
            s.login(address, pw)
            s.send_message(msg)
        print("[run_notify] email sent")
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[run_notify] email failed: {e}", file=sys.stderr)
        return False


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", required=True)
    ap.add_argument("--message", required=True)
    ap.add_argument("--subtitle", default=None)
    ap.add_argument("--sound", default="Glass")
    ap.add_argument("--email-subject", default=None)
    ap.add_argument("--email-body", default=None)
    ap.add_argument("--no-desktop", action="store_true")
    a = ap.parse_args()

    cfg = _notifications_config()
    address = (cfg.get("email") or "").strip()
    smtp_host = (cfg.get("smtp_host") or "").strip() or DEFAULT_SMTP_HOST

    # osascript is macOS-only; only fire when running on darwin and the user
    # has desktop notifications enabled in their config.
    if (
        not a.no_desktop
        and sys.platform == "darwin"
        and cfg.get("desktop_notifications") is True
    ):
        desktop(a.title, a.message, a.subtitle, a.sound)
    if a.email_subject:
        email(a.email_subject, a.email_body or a.message, address, smtp_host)


if __name__ == "__main__":
    main()
