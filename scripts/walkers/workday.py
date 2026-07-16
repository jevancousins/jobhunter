"""Workday `*.myworkdayjobs.com` walker.

Workday is significantly more complex than Greenhouse: most tenants require
account creation (email + password), multi-page forms (My Information,
Work Experience, Education, Voluntary Disclosures), and job-specific
screening.

Strategy:
1. Try the "Apply Manually" path on the job posting page.
2. If a sign-in dialog appears:
   a. Look up tenant credentials in Apple Passwords / macOS Keychain
      (via `_keychain.find_password(<tenant-host>)`). If found, sign in.
   b. If no credential is stored, auto-create an account: generate a
      strong password, fill email + password + verify, submit, and
      persist the credential to Apple Passwords via
      `_keychain.store_password(host, email, password)`. If the tenant
      gates on email verification, escalate so the edge-case agent can
      fetch the code from Gmail (the password is already saved).
3. If a "Create Account" dialog appears with no sign-in option, drive
   the same auto-create flow as 2(b).
4. If a single-page apply form appears, fill the standard fields and
   submit.
5. Otherwise escalate with a structured payload describing what was on
   screen so the edge-case sub-agent can reason about it.

Apple Passwords / Keychain integration:
   The user adds an entry to Apple Passwords (or macOS Keychain Access)
   for each Workday tenant they apply to, with the URL set to the
   tenant's host (e.g. `finastra.wd3.myworkdayjobs.com`). On first call
   from a binary, macOS prompts to allow `security` to read the entry —
   click "Always Allow" to make subsequent calls silent.
"""
from __future__ import annotations

import json
import re
import secrets
import string
import time
from pathlib import Path
from urllib.parse import urlparse

from . import _pcli as p
from . import _keychain


def _generate_password(length: int = 20) -> str:
    """Generate a Workday-compatible strong password.

    Most Workday tenants require >=8 chars with at least one upper, one
    lower, one digit, and one symbol. We pick from a restricted symbol set
    (`!@#$%&*?`) because some tenants reject characters like `<`, `>`, `"`.
    """
    upper = secrets.choice(string.ascii_uppercase)
    lower = secrets.choice(string.ascii_lowercase)
    digit = secrets.choice(string.digits)
    symbol = secrets.choice("!@#$%&*?")
    pool = string.ascii_letters + string.digits + "!@#$%&*?"
    rest = "".join(secrets.choice(pool) for _ in range(max(0, length - 4)))
    pw_chars = list(upper + lower + digit + symbol + rest)
    secrets.SystemRandom().shuffle(pw_chars)
    return "".join(pw_chars)


def _attempt_create_account(session: str, snap: str, host: str,
                              email: str) -> tuple[str, dict]:
    """Auto-create a Workday account and store the password in Apple
    Passwords / Keychain.

    Returns (status, detail) where status is one of:
      - "created"          account created, signed in, ready to apply
      - "verification"     account created but tenant gates on email
                           verification — escalate to edge-case agent
                           (which can fetch the code via Gmail MCP)
      - "create_failed"    couldn't drive the create-account form
    detail contains {"account": ..., "password": ..., "reason": ...}
    """
    # Click "Create Account" if it's a link/button rather than already shown
    create_ref = (_button_ref(snap, "Create Account")
                  or _link_ref(snap, "Create Account")
                  or _button_ref(snap, "Sign Up")
                  or _link_ref(snap, "Sign Up")
                  or _button_ref(snap, "Register"))
    if create_ref:
        p.click(session, create_ref)
        time.sleep(2)
        snap = p.snapshot(session)

    email_ref = (_textbox_ref(snap, "Email Address")
                 or _textbox_ref(snap, "Email"))
    pw_ref = _textbox_ref(snap, "Password")
    verify_ref = (_textbox_ref(snap, "Verify New Password")
                  or _textbox_ref(snap, "Verify Password")
                  or _textbox_ref(snap, "Confirm Password")
                  or _textbox_ref(snap, "Re-enter Password"))
    if not (email_ref and pw_ref):
        return ("create_failed", {"reason": "create-account-fields-not-found"})

    password = _generate_password()
    p.pcli(session, "fill", email_ref, email)
    time.sleep(0.2)
    p.pcli(session, "fill", pw_ref, password)
    time.sleep(0.2)
    if verify_ref:
        p.pcli(session, "fill", verify_ref, password)
        time.sleep(0.2)

    # Check the T&Cs / privacy checkbox if present (most Workday tenants
    # have one or two before allowing submit).
    for chk_label in ("I have read", "I agree", "Terms", "Privacy"):
        m = re.search(
            rf'checkbox "([^"]*{re.escape(chk_label)}[^"]*)"[^]]*\[ref=(e\d+)\]',
            snap, re.IGNORECASE,
        )
        if m:
            try:
                p.click(session, m.group(2))
                time.sleep(0.1)
            except Exception:
                pass

    # Persist the credential to Apple Passwords BEFORE submitting. If
    # submission fails or the tenant gates on email verification, the
    # password is already saved and a re-run can pick up where we left off.
    saved = _keychain.store_password(host, email, password,
                                       label=f"Workday — {host}")

    snap2 = p.snapshot(session)
    submit_ref = (_button_ref(snap2, "Create Account")
                  or _button_ref(snap2, "Sign Up")
                  or _button_ref(snap2, "Register")
                  or _button_ref(snap2, "Continue"))
    if not submit_ref:
        return ("create_failed", {
            "reason": "no-create-account-submit-button",
            "account": email, "password": password, "saved_to_keychain": saved,
        })
    p.click(session, submit_ref)
    time.sleep(4)

    snap3 = p.snapshot(session)

    if re.search(r"verify your email|verification (code|link|email)|"
                  r"check your (email|inbox)|confirmation email",
                  snap3, re.IGNORECASE):
        return ("verification", {
            "account": email, "password": password,
            "saved_to_keychain": saved,
            "reason": "email-verification-required",
        })

    if re.search(r"already (have an account|exists|in use)|"
                  r"email.*already.*registered",
                  snap3, re.IGNORECASE):
        return ("create_failed", {
            "reason": "email-already-registered-but-no-keychain-entry",
            "account": email, "password": password, "saved_to_keychain": saved,
        })

    if re.search(r"(password|email).*(invalid|incorrect|does not meet|"
                  r"must contain|must be at least)",
                  snap3, re.IGNORECASE):
        return ("create_failed", {
            "reason": "create-form-validation-error",
            "account": email, "password": password, "saved_to_keychain": saved,
        })

    return ("created", {
        "account": email, "password": password, "saved_to_keychain": saved,
    })

ROOT = Path(__file__).resolve().parent.parent.parent
PROFILE_PATH = ROOT / "data" / "application_profile.json"


def _load_profile() -> dict:
    return json.loads(PROFILE_PATH.read_text())


def _button_ref(snap: str, label: str) -> str | None:
    pat = re.compile(rf'button "([^"]*{re.escape(label)}[^"]*)" \[ref=(e\d+)\]', re.IGNORECASE)
    m = pat.search(snap)
    return m.group(2) if m else None


def _link_ref(snap: str, label: str) -> str | None:
    pat = re.compile(rf'link "([^"]*{re.escape(label)}[^"]*)" \[ref=(e\d+)\]', re.IGNORECASE)
    m = pat.search(snap)
    return m.group(2) if m else None


def _textbox_ref(snap: str, label: str) -> str | None:
    pat = re.compile(rf'textbox "([^"]*{re.escape(label)}[^"]*)" \[ref=(e\d+)\]', re.IGNORECASE)
    m = pat.search(snap)
    return m.group(2) if m else None


def _attempt_signin(session: str, snap: str, host: str,
                     fallback_email: str) -> tuple[str, str]:
    """Try to sign in to a Workday tenant using a credential from Apple
    Passwords / macOS Keychain. Returns (status, detail) where status is
    "signed_in" / "no_credential" / "signin_failed".
    """
    cred = _keychain.find_password(host)
    if not cred:
        # Try the bare hostname tenant prefix as a fallback (e.g. "finastra"
        # rather than "finastra.wd3.myworkdayjobs.com")
        tenant = host.split(".")[0] if host else ""
        if tenant:
            cred = _keychain.find_password(tenant)
    if not cred:
        return ("no_credential", "")

    account = cred.get("account") or fallback_email
    password = cred["password"]

    # Find email + password fields on the sign-in form
    email_ref = (_textbox_ref(snap, "Email Address")
                 or _textbox_ref(snap, "Email")
                 or _textbox_ref(snap, "Username"))
    pw_ref = _textbox_ref(snap, "Password")
    if not (email_ref and pw_ref):
        return ("signin_failed", "email-or-password-field-not-found")

    p.pcli(session, "fill", email_ref, account)
    time.sleep(0.2)
    p.pcli(session, "fill", pw_ref, password)
    time.sleep(0.2)

    # Click Sign In
    snap2 = p.snapshot(session)
    signin_ref = (_button_ref(snap2, "Sign In")
                  or _button_ref(snap2, "Log In")
                  or _button_ref(snap2, "Login")
                  or _button_ref(snap2, "Continue"))
    if not signin_ref:
        return ("signin_failed", "no-signin-button")
    p.click(session, signin_ref)
    time.sleep(4)

    # Verify we're past the sign-in page
    snap3 = p.snapshot(session)
    if re.search(r"(Invalid|incorrect|wrong) (email|password|credentials)|"
                  r"could not (sign|log) (you )?in",
                  snap3, re.IGNORECASE):
        return ("signin_failed", "credentials-rejected")
    if re.search(r"Sign In|Password", snap3) and "Sign Out" not in snap3:
        # still on sign-in page → signin didn't take
        return ("signin_failed", "still-on-signin-page")
    return ("signed_in", "ok")


def walk(role_context: dict, cv_pdf: Path, session_name: str) -> dict:
    apply_url = role_context.get("apply_type", "")
    if apply_url.startswith("EXT:"):
        apply_url = apply_url[4:]
    if not apply_url:
        return {"status": "failed", "reason": "no-apply-url"}

    host = urlparse(apply_url).hostname or ""
    p.goto(session_name, apply_url, settle=4)
    snap = p.snapshot(session_name)

    # Step 0: detect expired / 404 job pages before doing anything else.
    # Workday renders a generic "page not found" message when a requisition
    # has been closed or the URL is stale — these are not account-required
    # failures and should be marked Expired rather than Escalated.
    body_text = p.pcli_eval(session_name, "(() => (document.body.innerText || '').slice(0, 3000))()")
    if isinstance(body_text, str) and re.search(
        r"page.*you.*looking for.*doesn.t exist"
        r"|page.*not found"
        r"|this job.*no longer.*available"
        r"|position.*has been filled"
        r"|posting.*has.*expired"
        r"|requisition.*is.*closed"
        r"|job.*is.*closed"
        r"|no longer accepting",
        body_text, re.IGNORECASE,
    ):
        return {
            "status": "expired",
            "reason": "workday-job-not-found-or-expired",
            "payload": {
                "url": apply_url,
                "host": host,
                "note": "Workday returned a 'page not found' or job-closed "
                        "message. The requisition is likely expired.",
            },
        }

    # Step 1: find and click the "Apply" button on the posting
    apply_ref = _button_ref(snap, "Apply")
    if apply_ref:
        p.click(session_name, apply_ref)
        time.sleep(2)
        snap = p.snapshot(session_name)

    # Step 2: prefer "Apply Manually" if a chooser is visible
    manual_ref = _button_ref(snap, "Apply Manually") or _link_ref(snap, "Apply Manually")
    if manual_ref:
        p.click(session_name, manual_ref)
        time.sleep(2)
        snap = p.snapshot(session_name)

    # Step 3: detect sign-in / account-creation walls
    has_signin = bool(re.search(r"Sign In|Email Address.*Password", snap, re.IGNORECASE | re.DOTALL))
    has_create = bool(re.search(r"Create Account|Sign Up|Register", snap, re.IGNORECASE))
    # host was already computed at the top of walk()

    if has_signin:
        # Try Apple Passwords / Keychain. If a credential exists, sign in
        # and continue to the application form. If not, escalate so the
        # user can create the account in Apple Passwords first.
        profile_for_email = _load_profile()["identity"]["email"]
        signin_status, detail = _attempt_signin(session_name, snap, host,
                                                  fallback_email=profile_for_email)
        if signin_status == "signed_in":
            time.sleep(1)
            snap = p.snapshot(session_name)
            # Fall through to the application form handling below
        elif signin_status == "no_credential":
            # No stored credential. Try to auto-create an account so future
            # runs can sign in via Apple Passwords lookup.
            create_status, create_detail = _attempt_create_account(
                session_name, snap, host, profile_for_email,
            )
            if create_status == "created":
                time.sleep(1)
                snap = p.snapshot(session_name)
                # fall through to apply form handling
            elif create_status == "verification":
                return {
                    "status": "escalate",
                    "reason": "workday-account-created-needs-email-verification",
                    "payload": {
                        "host": host,
                        "url": apply_url,
                        "account": create_detail.get("account"),
                        "saved_to_keychain": create_detail.get("saved_to_keychain"),
                        "note": (f"Account created on {host}; tenant requires "
                                 f"email verification before login. Edge-case "
                                 f"agent should fetch the verification code/link "
                                 f"from Gmail (look for sender containing "
                                 f"'{host}' or 'workday') and follow it. The "
                                 f"password is already stored in Apple Passwords "
                                 f"under URL='{host}'."),
                    },
                }
            else:
                return {
                    "status": "escalate",
                    "reason": "workday-account-creation-failed",
                    "payload": {
                        "host": host,
                        "url": apply_url,
                        "detail": create_detail,
                        "note": (f"Tried to auto-create a Workday account on "
                                 f"{host} but the create-account flow could not "
                                 f"be driven: {create_detail.get('reason')}. "
                                 f"Sub-agent should inspect the page."),
                    },
                }
        else:
            return {
                "status": "escalate",
                "reason": "workday-signin-failed",
                "payload": {
                    "host": host,
                    "url": apply_url,
                    "detail": detail,
                    "note": (f"Apple Passwords entry was found for {host} but "
                             f"sign-in failed: {detail}. The credential may be "
                             f"stale. Update it in Apple Passwords and re-run."),
                },
            }
    elif has_create:
        # Pure account-creation flow. Drive it directly and store the
        # password in Apple Passwords.
        profile_for_email = _load_profile()["identity"]["email"]
        create_status, create_detail = _attempt_create_account(
            session_name, snap, host, profile_for_email,
        )
        if create_status == "created":
            time.sleep(1)
            snap = p.snapshot(session_name)
        elif create_status == "verification":
            return {
                "status": "escalate",
                "reason": "workday-account-created-needs-email-verification",
                "payload": {
                    "host": host, "url": apply_url,
                    "account": create_detail.get("account"),
                    "saved_to_keychain": create_detail.get("saved_to_keychain"),
                    "note": (f"Account created on {host}; tenant requires "
                             f"email verification. Edge-case agent should "
                             f"fetch the verification code/link from Gmail "
                             f"and follow it. Password already stored in "
                             f"Apple Passwords under URL='{host}'."),
                },
            }
        else:
            return {
                "status": "escalate",
                "reason": "workday-account-creation-failed",
                "payload": {
                    "host": host, "url": apply_url, "detail": create_detail,
                    "note": (f"Tried to auto-create a Workday account on "
                             f"{host}: {create_detail.get('reason')}. "
                             f"Sub-agent should inspect the page."),
                },
            }

    # Step 4: detect "Use my LinkedIn" path — too brittle to drive deterministically
    if re.search(r"Use my LinkedIn|Apply with LinkedIn", snap, re.IGNORECASE):
        return {
            "status": "escalate",
            "reason": "workday-prefers-linkedin-import",
            "payload": {"url": apply_url,
                        "note": "Workday is offering the LinkedIn-import path; "
                                "sub-agent should navigate the multi-page form "
                                "manually."},
        }

    # Step 5: if a single-page form is detected (My Information visible inline
    # on the apply URL), attempt the common fields. Most tenants don't allow
    # this — they push to multi-page wizards — so this branch is best-effort.
    profile = _load_profile()
    ident = profile["identity"]

    name_pat = re.compile(r'textbox "(First Name|Legal First Name)"[^]]*\[ref=(e\d+)\]')
    if name_pat.search(snap):
        # try the common fields
        for label, value in (
            ("First Name", ident["first_name"]),
            ("Legal First Name", ident["first_name"]),
            ("Last Name", ident["last_name"]),
            ("Legal Last Name", ident["last_name"]),
            ("Email Address", ident["email"]),
            ("Email", ident["email"]),
            ("Phone Number", ident["phone"]),
        ):
            m = re.search(rf'textbox "{re.escape(label)}"[^]]*\[ref=(e\d+)\]', snap)
            if m and value:
                p.pcli(session_name, "fill", m.group(1), value)
                time.sleep(0.2)

        # CV upload — typically a "Drop files here" zone with hidden file input
        upload_btn = _button_ref(snap, "Upload") or _button_ref(snap, "Attach Resume")
        if upload_btn:
            p.click(session_name, upload_btn)
            time.sleep(0.5)
            p.upload(session_name, cv_pdf)
            time.sleep(2)

        # submit attempt
        snap = p.snapshot(session_name)
        submit_ref = _button_ref(snap, "Submit") or _button_ref(snap, "Continue")
        if submit_ref:
            p.click(session_name, submit_ref)
            time.sleep(3)
            snap = p.snapshot(session_name)
            confirmed = p.pcli_eval(
                session_name,
                "(() => /Application submitted|received your application|Thank you/i.test(document.body.innerText))()",
            )
            if confirmed:
                return {
                    "status": "applied",
                    "submitted_via": "Workday",
                    "confirmation": "Application submitted",
                    "screening": {"first_name": ident["first_name"],
                                  "last_name": ident["last_name"],
                                  "email": ident["email"]},
                }
            # multi-page wizard ahead — escalate with state
            return {
                "status": "escalate",
                "reason": "workday-multipage-after-info",
                "payload": {"url": apply_url,
                            "note": "Filled My Info / uploaded CV but the form "
                                    "advanced to a subsequent page. Sub-agent "
                                    "must complete remaining pages."},
            }

    # Step 6: nothing recognised — escalate with snapshot tail for diagnosis
    return {
        "status": "escalate",
        "reason": "workday-form-shape-unknown",
        "payload": {
            "url": apply_url,
            "snapshot_tail": snap[-2000:],
            "note": "Walker did not recognise sign-in, manual-apply, or "
                    "single-page form patterns. Sub-agent must drive directly.",
        },
    }
