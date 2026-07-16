"""captcha_preflight.py -- pre-flight captcha detection for ATS apply URLs.

Detection uses two complementary strategies:

1. **Host-pattern denylist** (``CAPTCHA_HOSTS``): ATS hostnames that are
   *always* captcha-walled regardless of the specific job URL.  iCIMS and
   Njoyn/CGI load their captcha widgets entirely via JavaScript, so a static
   HTML fetch cannot see them.  Matching the hostname is cheaper, faster, and
   more reliable for those platforms.

2. **Static HTML scan** (``CAPTCHA_MARKERS``): Fetches the page HTML and
   scans for known captcha marker strings.  Catches CDN-level gates such as
   Radware Bot Manager, which return a captcha page *before* any JavaScript
   executes.

Both checks are combined in ``has_captcha()``.  The host check runs first
(no network round-trip).  If it fires the URL is blocked immediately.  The
HTML scan is only attempted when the host is not already on the denylist.

Usage::

    from walkers.captcha_preflight import has_captcha, CAPTCHA_REASON

    url = apply_type[4:]   # strip leading "EXT:"
    found, marker = has_captcha(url)
    if found:
        return finish({"status": "failed", "reason": CAPTCHA_REASON,
                       "captcha_marker": marker})

Public API
----------
has_captcha(url, *, timeout=10) -> tuple[bool, str | None]
    Returns ``(True, detection_tag)`` if a captcha wall is found, or
    ``(False, None)`` otherwise.  Fails open on network errors so transient
    failures do not silently skip roles.

CAPTCHA_REASON : str
    Canonical failure-reason tag (``"captcha-protected-form"``) used when
    recording the result in Notion / diagnostics.

CAPTCHA_HOSTS : frozenset[str]
    Hostname suffixes always treated as captcha-walled (host-pattern denylist).

CAPTCHA_MARKERS : tuple[str, ...]
    HTML substrings that trigger a positive static-scan result.
"""
from __future__ import annotations

import logging
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Canonical result tag
# ---------------------------------------------------------------------------
CAPTCHA_REASON: str = "captcha-protected-form"

# ---------------------------------------------------------------------------
# Host-pattern denylist
# ---------------------------------------------------------------------------
# These ATS platforms inject their captcha widgets entirely via JavaScript.
# A static HTML GET cannot see the captcha markup, so we match on hostname
# instead.  Only hostname *suffixes* are listed (subdomain-safe matching).
#
# Evidence source (2026-05-22 drain-queue run):
#   - iCIMS: hCaptcha loaded via JS on every apply-form page.
#   - Njoyn (CGI): Radware Bot Manager returns a captcha page at the CDN
#     level for automated UA strings, but the marker shows up in static HTML
#     only for some CGI sub-tenants.  Listed here for belt-and-braces coverage.
#   - Ashby: reCAPTCHA Enterprise triggered on headless sessions; HTML scan
#     reliably misses it on initial page load.
CAPTCHA_HOSTS: frozenset[str] = frozenset(
    [
        # iCIMS -- hCaptcha on apply gate, JS-rendered
        "icims.com",
        # Njoyn / CGI -- Radware captcha (some tenants serve it via JS)
        "njoyn.com",
    ]
)

# ---------------------------------------------------------------------------
# HTML markers for static scan
# ---------------------------------------------------------------------------
# Lower-cased substrings searched in the full response body.
#
# IMPORTANT: do NOT add the bare word "recaptcha" here.  Greenhouse and
# other automatable ATSes include "GOOGLE_RECAPTCHA_INVISIBLE_KEY" or similar
# config constants in their page HTML as part of their JS bundle -- this
# causes false positives.  Use only the more specific forms below.
CAPTCHA_MARKERS: tuple[str, ...] = (
    # reCAPTCHA widget elements (NOT the bare word "recaptcha")
    "g-recaptcha",       # <div class="g-recaptcha" ...>
    "grecaptcha",        # window.grecaptcha API reference in active widget JS
    "captcha-token",     # hidden input injected by reCAPTCHA on completion
    # hCaptcha (image challenges, drag puzzles)
    "hcaptcha",
    "h-captcha",
    # Radware Bot Manager / ShieldSquare (static CDN-level gate)
    "radware",
    "rdprotect",
    "rddebug",
    "shieldsquare",
    "captcha.perfdrive.com",  # Radware challenge asset CDN
    # Generic data-sitekey attribute (both reCAPTCHA and hCaptcha use this)
    "data-sitekey",
    # Cloudflare Turnstile
    "cf-turnstile",
    # Generic captcha widget identifiers seen in some ATSes
    "captcha-container",
    "captcha_challenge",
    "captcha-widget",
)

# ---------------------------------------------------------------------------
# HTML-scan exclusion list
# ---------------------------------------------------------------------------
# Hosts whose HTML pages include captcha-adjacent strings (e.g. config keys
# in JS bundles) but are NOT actually captcha-walled at the static-fetch
# level.  The HTML scan is skipped for these; our existing walkers handle
# any runtime captcha they encounter.
HTML_SCAN_EXCLUDE_HOSTS: frozenset[str] = frozenset(
    [
        # Greenhouse includes GOOGLE_RECAPTCHA_INVISIBLE_KEY in its page JS
        # bundle -- not a captcha gate; our greenhouse walker handles the form.
        "boards.greenhouse.io",
        "greenhouse.io",
        # Lever embeds reCAPTCHA metadata in its job-page HTML but the walker
        # drives the form successfully in most cases.
        "jobs.lever.co",
        "lever.co",
        # Ashby -- captcha only triggers on headless submit, not on page load.
        # The ashby walker already handles this; pre-flight would false-positive.
        "jobs.ashbyhq.com",
        "ashbyhq.com",
    ]
)

# ---------------------------------------------------------------------------
# Request headers
# ---------------------------------------------------------------------------
_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}


def _host_is_captcha_walled(url: str) -> tuple[bool, str | None]:
    """Return (True, tag) if the URL's hostname matches CAPTCHA_HOSTS."""
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return False, None
    for suffix in CAPTCHA_HOSTS:
        if host == suffix or host.endswith("." + suffix):
            return True, f"known-captcha-host:{suffix}"
    return False, None


def _html_has_captcha(url: str, timeout: int) -> tuple[bool, str | None]:
    """Fetch *url* and scan the HTML body for CAPTCHA_MARKERS.

    Returns (False, None) on any network / HTTP error (fail-open).
    """
    try:
        import httpx  # already in requirements.txt; imported lazily
    except ImportError:
        logger.warning("captcha_preflight: httpx not available; skipping HTML scan")
        return False, None

    try:
        with httpx.Client(
            follow_redirects=True,
            timeout=timeout,
            headers=_HEADERS,
            verify=False,  # some ATS certs cause SNI issues; content-only fetch
        ) as client:
            response = client.get(url)
    except Exception as exc:
        logger.debug("captcha_preflight: fetch failed for %s: %s", url, exc)
        return False, None

    body_lower = response.text.lower()
    for marker in CAPTCHA_MARKERS:
        if marker in body_lower:
            logger.info(
                "captcha_preflight: HTML marker=%r found in %s (HTTP %s)",
                marker,
                url,
                response.status_code,
            )
            return True, marker

    return False, None


def _host_is_html_scan_excluded(url: str) -> bool:
    """Return True if the URL's host is on the HTML-scan exclusion list."""
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return False
    for suffix in HTML_SCAN_EXCLUDE_HOSTS:
        if host == suffix or host.endswith("." + suffix):
            return True
    return False


def has_captcha(url: str, *, timeout: int = 10) -> tuple[bool, str | None]:
    """Return (captcha_found, detection_tag_or_None).

    Detection order:
    1. Host-pattern denylist (CAPTCHA_HOSTS) -- no network round-trip.
    2. Static HTML scan (CAPTCHA_MARKERS) -- skipped for hosts in
       HTML_SCAN_EXCLUDE_HOSTS to avoid false positives.

    Returns (False, None) if:
    - The URL is empty or not HTTP(S).
    - The host is not on the denylist AND the HTML scan finds no markers.
    - The host is on HTML_SCAN_EXCLUDE_HOSTS (neither check fires).
    - Any network error occurs during the HTML scan (fail-open).

    Returns (True, tag) where *tag* is:
    - ``"known-captcha-host:<suffix>"`` when matched via CAPTCHA_HOSTS.
    - A matching string from CAPTCHA_MARKERS when found in page HTML.
    """
    if not url or not url.startswith(("http://", "https://")):
        return False, None

    # 1. Host-pattern denylist (fast, no network)
    found, tag = _host_is_captcha_walled(url)
    if found:
        logger.info("captcha_preflight: host-denylist match tag=%r for %s", tag, url)
        return True, tag

    # 2. Static HTML scan (skip for excluded hosts to avoid false positives)
    if _host_is_html_scan_excluded(url):
        logger.debug("captcha_preflight: HTML scan excluded for %s", url)
        return False, None

    return _html_has_captcha(url, timeout)
