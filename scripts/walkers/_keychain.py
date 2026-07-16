"""macOS Keychain / Apple Passwords helper for ATS-account credentials.

Reads internet-password entries via the macOS `security` CLI. Apple Passwords
synced from iCloud appear in the login keychain as `internet-password` items
keyed by the URL field — so storing a password in Apple Passwords with the
URL `<tenant>.myworkdayjobs.com` (or just `<tenant>`) makes it findable here.

First call from a given binary may trigger a one-time macOS prompt asking
the user to allow `security` to access the keychain. Click "Always Allow"
to suppress the prompt for subsequent calls. (This is a system-level UX,
not something we can dismiss programmatically.)

Public API:
    find_password(host: str, account: str | None = None) -> dict | None
        Returns {"account": <user>, "password": <pw>, "host": <host>}
        or None if no entry is found.
    store_password(host, account, password) -> bool
        Convenience helper to write an entry programmatically (rare —
        normally entries are created in Apple Passwords by the user).
"""
from __future__ import annotations

import shutil
import subprocess
from typing import Optional


def _have_security_cli() -> bool:
    return shutil.which("security") is not None


def find_password(host: str, account: Optional[str] = None) -> Optional[dict]:
    """Look up an internet-password entry by host (and optionally account).

    The macOS Keychain matches `-s <host>` against the "Where" / URL field
    of the entry. If multiple entries share a host, pass `account` to
    disambiguate; otherwise the first match is returned.
    """
    if not _have_security_cli():
        return None
    cmd = ["security", "find-internet-password", "-s", host, "-w"]
    if account:
        cmd[3:3] = ["-a", account]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    if res.returncode != 0:
        return None
    pw = res.stdout.strip()
    if not pw:
        return None

    # Look up the account name separately (the `-w` flag returns only the pw)
    cmd_meta = ["security", "find-internet-password", "-s", host]
    if account:
        cmd_meta[3:3] = ["-a", account]
    meta = subprocess.run(cmd_meta, capture_output=True, text=True, timeout=15)
    acct = account or ""
    if meta.returncode == 0:
        for line in meta.stdout.splitlines():
            line = line.strip()
            if line.startswith('"acct"<blob>='):
                # format: "acct"<blob>="user@example.com"
                acct = line.split("=", 1)[1].strip().strip('"')
                break
    return {"account": acct, "password": pw, "host": host}


def store_password(host: str, account: str, password: str,
                    label: Optional[str] = None) -> bool:
    """Add an internet-password entry. Mostly here for completeness; in
    practice users add entries via Apple Passwords UI. Returns True on
    success."""
    if not _have_security_cli():
        return False
    cmd = [
        "security", "add-internet-password",
        "-s", host,
        "-a", account,
        "-w", password,
        "-T", "",  # no app whitelist; relies on user's "Always Allow" click
        "-U",      # update if exists
    ]
    if label:
        cmd.extend(["-l", label])
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    return res.returncode == 0
