#!/usr/bin/env python3
"""auto_apply.py — Python orchestrator for the auto-apply pipeline.

Architecture: this module owns ALL deterministic work (LinkedIn search,
filtering, dedup, role-folder prep, form-walking for known ATS, Notion
state transitions, summary). LLM-requiring steps (CV tailoring, cover
letters, edge cases) are handled by Claude Code sub-agents invoked by the
main orchestrator session — this script does NOT call any LLM API.

Notion is the single source of truth. Each role moves through:

    NeedsTailoring  ──> ReadyToApply  ──> Applied
                                    └──> Escalated   (manual/edge-case)
                                    └──> Failed      (terminal error)

The script is idempotent and resumable. Each subcommand reads/writes
state from Notion and the per-role folder under applications/<id>/.

Subcommands
-----------
session-open      Open the playwright-cli session and load LinkedIn auth.
session-close     Close the playwright-cli session.
search            Run search across one or more LinkedIn URLs; filter; write
                  APPLY rows to Notion as NeedsTailoring.
list-queue        Print role IDs in a given Notion Status, as JSON.
prepare           For one role: ensure jd.txt + role-context.json exist,
                  select variant, copy template PDF as fallback. Fresh search
                  rows already have local files; older Notion/import rows are
                  hydrated from Notion and may require --jd-file/--jd-text if
                  Notion has no Job Description. The role-tailorer sub-agent
                  then produces the employer-named CV PDF in the same folder.
mark-ready        Set Notion Status="ReadyToApply" for a role. Renames any
                  legacy cv.pdf to the employer-facing name. Watchlist
                  companies require a real tailored CV and cannot use the
                  template fallback.
apply             Drive the form for one role using the matching ATS walker.
                  Prints a JSON result: {status: applied|escalate|failed, ...}.
mark-applied      Set Status="Applied" + write submission-log.json.
mark-escalated    Set Status="Escalated" with reason.
mark-failed       Set Status="Failed" with reason.
summary           Print a markdown summary of today's run.

Examples
--------
    python scripts/auto_apply.py session-open
    python scripts/auto_apply.py search --date 24h \
        --location <keys-from-search.locations>
    python scripts/auto_apply.py list-queue --status NeedsTailoring
    python scripts/auto_apply.py prepare --role 4409861209
    # (orchestrator main session invokes role-tailorer sub-agent here)
    python scripts/auto_apply.py mark-ready --role 4409861209
    python scripts/auto_apply.py apply --role 4409861209
    python scripts/auto_apply.py mark-applied --role 4409861209
    python scripts/auto_apply.py summary
    python scripts/auto_apply.py session-close
"""
from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from user_config import autonomy_level, load_search_config, require_autonomy

ROOT = Path(__file__).resolve().parent.parent
APPLICATIONS_DIR = ROOT / "applications"

# All user-specific tuning lives in data/search_config.json (created from
# data/search_config.example.json by the /onboard skill). load_search_config
# exits with guidance if the file is missing.
_CONFIG = load_search_config()
_CANDIDATE_CFG = _CONFIG.get("candidate", {})
_SEARCH_CFG = _CONFIG.get("search", {})


def _sanitize_company(company: str) -> str:
    """Filesystem-safe company folder name.

    Strips and collapses whitespace; replaces filesystem-reserved chars with '-'.
    """
    if not company:
        return "_Unknown"
    s = company.strip()
    for ch in '/\\:*?"<>|':
        s = s.replace(ch, "-")
    s = " ".join(s.split())
    return s or "_Unknown"


def resolve_role_dir(rid: str, company: str | None = None) -> Path:
    """Resolve the per-role folder under applications/.

    New layout is `applications/<Company>/<role-id>/`. Legacy flat layout
    `applications/<role-id>/` is still honoured for in-progress migration:
    if a flat folder exists it is returned as-is.

    When `company` is supplied AND no existing folder is found, the nested
    `applications/<Company>/<role-id>/` path is returned (for callers that
    will mkdir it). When `company` is omitted and nothing exists, the
    legacy flat path is returned.
    """
    flat = APPLICATIONS_DIR / rid
    if flat.is_dir():
        return flat
    # Try nested lookup via glob (cheap: ~600 company dirs).
    for cand in APPLICATIONS_DIR.glob(f"*/{rid}"):
        if cand.is_dir():
            return cand
    if company:
        return APPLICATIONS_DIR / _sanitize_company(company) / rid
    return flat


def iter_role_dirs():
    """Yield every per-role folder regardless of layout (flat or nested)."""
    seen = set()
    for sub in APPLICATIONS_DIR.iterdir():
        if not sub.is_dir() or sub.name.startswith("."):
            continue
        rc = sub / "role-context.json"
        if rc.exists():
            yield sub
            seen.add(sub)
            continue
        # Treat as company folder; yield its children
        for child in sub.iterdir():
            if child.is_dir() and child not in seen:
                yield child
RUNS_DIR = ROOT / "data" / "auto-apply-runs"
CV_OUTPUT_DIR = ROOT / "cv" / "output"
SESSION_NAME = "auto-apply"
LINKEDIN_STATE = ROOT / "data" / ".linkedin-state.json"
# Employer-facing CV basename, e.g. "Alex Example CV". Configured via
# cv.employer_filename_base, falling back to "<candidate.display_name> CV".
EMPLOYER_CV_BASENAME = (
    _CONFIG.get("cv", {}).get("employer_filename_base")
    or (f"{_CANDIDATE_CFG['display_name']} CV"
        if _CANDIDATE_CFG.get("display_name") else None)
)
if not EMPLOYER_CV_BASENAME:
    raise SystemExit(
        "cv.employer_filename_base (or candidate.display_name) missing from "
        "data/search_config.json. Run /onboard or edit the file."
    )
EMPLOYER_CV_NAME = f"{EMPLOYER_CV_BASENAME}.pdf"
INTELLIGENCE_PATH = ROOT / "data" / "apply-intelligence.json"

# Daily cap on LinkedIn Apply submissions, from autonomy.max_daily_linkedin_applications.
MAX_DAILY_LINKEDIN_APPLICATIONS = int(
    _CONFIG.get("autonomy", {}).get("max_daily_linkedin_applications", 25)
)

_intelligence_cache: dict | None = None


def _load_intelligence() -> dict:
    """Load the intelligence file (cached per process)."""
    global _intelligence_cache
    if _intelligence_cache is not None:
        return _intelligence_cache
    if not INTELLIGENCE_PATH.exists():
        _intelligence_cache = {}
        return _intelligence_cache
    try:
        with INTELLIGENCE_PATH.open() as f:
            _intelligence_cache = json.load(f)
    except (json.JSONDecodeError, OSError):
        _intelligence_cache = {}
    return _intelligence_cache

# Status values written to Notion. These MUST exactly match the option names
# in the Notion Jobs DB Status field (which is now `type: "status"`, organised
# into to_do / in_progress / complete groups). Source of truth as of 2026-05-03:
#   to_do:        ToReview, Consider, Apply, NeedsTailoring, ReadyToApply,
#                 Escalated, Failed
#   in_progress:  AwaitingResponse, ResponseReceived, PhoneScreen, Test,
#                 CultureInterview, TechnicalInterview, FinalRound, Offer
#   complete:     Expired, NoResponse, Rejected, Skip, Accepted
STATUS_NEEDS_TAILORING = "NeedsTailoring"
STATUS_READY_TO_APPLY = "ReadyToApply"
# Post-submit state. There is intentionally no "Applied" terminal status any
# more — every successful submission moves into the in_progress group as
# AwaitingResponse and progresses from there based on what arrives by email.
STATUS_AWAITING_RESPONSE = "AwaitingResponse"
STATUS_ESCALATED = "Escalated"
STATUS_FAILED = "Failed"
STATUS_EXPIRED = "Expired"
STATUS_SKIP = "Skip"

# All Notion Status options that should be treated as "this LinkedIn job is
# already in our system, do not re-apply." Used by search-phase dedup.
KNOWN_NOTION_STATUSES = (
    # to_do
    "ToReview", "Consider", "Apply",
    STATUS_NEEDS_TAILORING, STATUS_READY_TO_APPLY,
    STATUS_ESCALATED, STATUS_FAILED,
    # in_progress
    STATUS_AWAITING_RESPONSE, "ResponseReceived",
    "PhoneScreen", "Test", "CultureInterview",
    "TechnicalInterview", "FinalRound", "Offer",
    # complete
    STATUS_EXPIRED, "NoResponse", "Rejected", STATUS_SKIP, "Accepted",
)


# Companies never to apply to (e.g. the current employer and its
# subsidiaries), from filters.company_blacklist. Optional; defaults empty.
COMPANY_BLACKLIST = tuple(_CONFIG.get("filters", {}).get("company_blacklist") or ())

# Notion statuses that indicate an active interview process.
IN_PROCESS_STATUSES = (
    "PhoneScreen", "Test", "CultureInterview",
    "TechnicalInterview", "FinalRound", "Offer",
)


# ---------------------------------------------------------------------------
# helper imports (the existing deterministic scripts loaded as modules so we
# avoid the subprocess + pyenv-shim cost on hot loops)
# ---------------------------------------------------------------------------

def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_qf = _load_module("quick_filter", ROOT / "scripts" / "quick_filter.py")
_sv = _load_module("select_variant", ROOT / "scripts" / "select_variant.py")


# ---------------------------------------------------------------------------
# Haiku realism check
# ---------------------------------------------------------------------------

_HAIKU_REALISM_PROMPT = """\
You are a strict filter for a job search system. Decide if this role is realistic for the candidate.

Candidate: {candidate_summary}

Hard UNREALISTIC signals (any one of these = UNREALISTIC):
- The JD's core skill or technology requirements have no overlap with the candidate's background
- JD is for a specialised industry the candidate has never worked in and requires domain expertise
- Role requires 5+ years in a specific technical domain the candidate has never worked in
- Role requires domain expertise the candidate definitely lacks (e.g. actuarial, legal, biomedical research)

Soft UNREALISTIC signals (two or more = UNREALISTIC):
- JD explicitly lists 6+ years required and the role is in a domain the candidate has under 2 years in
- JD requires certifications or credentials the candidate clearly cannot have (e.g. CFA, bar exam, medical licence)

Everything else = REALISTIC (default to REALISTIC when uncertain).

Job title: {title}
Job description (first 1200 chars):
{description}

Reply with exactly one line: REALISTIC or UNREALISTIC, then a colon, then a brief reason (max 15 words).
Example: UNREALISTIC: requires 6+ years in a stack the candidate has never used
Example: REALISTIC: core requirements match the candidate's background
"""


def _haiku_realism_check(title: str, description: str) -> tuple[bool, str]:
    """Returns (is_realistic, reason). Defaults to (True, 'check-skipped') on error."""
    candidate_summary = (_CANDIDATE_CFG.get("summary") or "").strip()
    if not candidate_summary:
        # Fail open, consistent with the error path below, but say why so the
        # user knows to populate candidate.summary in data/search_config.json.
        return True, "check-skipped: candidate.summary missing from data/search_config.json"
    try:
        import anthropic
        client = anthropic.Anthropic()
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=60,
            messages=[{
                "role": "user",
                "content": _HAIKU_REALISM_PROMPT.format(
                    candidate_summary=candidate_summary,
                    title=title,
                    description=description[:1200],
                ),
            }],
        )
        text = (msg.content[0].text if msg.content else "").strip()
        is_realistic = text.upper().startswith("REALISTIC")
        reason = text.split(":", 1)[-1].strip() if ":" in text else text
        return is_realistic, reason
    except Exception as e:
        return True, f"check-skipped: {e}"


# ---------------------------------------------------------------------------
# playwright-cli helpers
# ---------------------------------------------------------------------------

def pcli(*args: str, capture: bool = True, timeout: int = 60) -> str:
    cmd = ["playwright-cli", f"-s={SESSION_NAME}", *args]
    res = subprocess.run(
        cmd,
        capture_output=capture,
        text=True,
        timeout=timeout,
    )
    return res.stdout


def pcli_eval(js: str, timeout: int = 60) -> Any:
    """Run an `eval` in the playwright-cli session and return the parsed result.

    `--raw` prints just the value. The first JSON.parse handles the outer
    string wrapper; if the inner value is itself JSON-encoded (returned via
    JSON.stringify in the eval), parse a second time.
    """
    out = pcli("eval", js, "--raw", timeout=timeout)
    out = out.strip()
    if not out:
        return None
    try:
        val = json.loads(out)
    except json.JSONDecodeError:
        return out
    if isinstance(val, str):
        try:
            return json.loads(val)
        except json.JSONDecodeError:
            return val
    return val


# ---------------------------------------------------------------------------
# Notion helpers (delegated to scripts/notion_cli.py to keep schema knowledge
# in one place)
# ---------------------------------------------------------------------------

def notion_run(*args: str) -> str:
    cmd = [sys.executable, str(ROOT / "scripts" / "notion_cli.py"), *args]
    res = None
    transient_markers = (
        "ConnectError",
        "ConnectTimeout",
        "ReadTimeout",
        "RemoteProtocolError",
        "Temporary failure",
        "nodename nor servname",
    )
    for attempt in range(3):
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if res.returncode == 0:
            break
        if not any(marker in res.stderr for marker in transient_markers):
            break
        if attempt < 2:
            time.sleep(2 * (attempt + 1))
    assert res is not None
    if res.returncode != 0:
        raise RuntimeError(f"notion_cli failed: {res.stderr}")
    # structlog logs to stdout too; strip those lines and return the JSON body
    lines = res.stdout.splitlines()
    start = None
    for i, ln in enumerate(lines):
        s = ln.lstrip()
        if s.startswith("{") or s.startswith("["):
            start = i
            break
    if start is None:
        return res.stdout
    return "\n".join(lines[start:])


SEEN_IDS_PATH = ROOT / "data" / "seen_job_ids.json"
WATCHLIST_CACHE_PATH = ROOT / "data" / "company_watchlist_cache.json"


def _load_seen_ids() -> set[str]:
    """Load the local seen-IDs cache (jd_skip / jd_empty roles from prior runs)."""
    if not SEEN_IDS_PATH.exists():
        return set()
    try:
        return set(json.loads(SEEN_IDS_PATH.read_text()).get("ids", []))
    except Exception:
        return set()


def _record_seen_ids(job_ids: list[str]) -> None:
    """Append job IDs to the local seen-IDs cache so they are treated as
    duplicates on the next search run and dismissed at the duplicate-check
    stage (before any JD navigation), where dismissal works reliably."""
    existing = _load_seen_ids()
    new_ids = [jid for jid in job_ids if jid not in existing]
    if new_ids:
        all_ids = sorted(existing | set(new_ids))
        SEEN_IDS_PATH.write_text(json.dumps({"ids": all_ids}, indent=2))


def notion_known_linkedin_ids() -> set[str]:
    """All LinkedIn job IDs already seen — from Notion (all statuses) and the
    local seen-IDs cache (jd_skip / jd_empty roles not written to Notion).
    Search dedup never re-applies to the same role."""
    ids: set[str] = _load_seen_ids()
    for status in KNOWN_NOTION_STATUSES:
        try:
            out = notion_run("list-by-status", status)
            data = json.loads(out)
        except Exception:
            continue
        for j in data:
            url = j.get("url") or ""
            m = re.search(r"/jobs/view/(\d+)", url)
            if m:
                ids.add(m.group(1))
    return ids


_COMPANY_SUFFIX_RE = re.compile(
    r"\b(inc|incorporated|ltd|limited|llc|plc|corp|corporation|company|co|"
    r"gmbh|sas|sa|ag|se)\b\.?",
    re.IGNORECASE,
)


def _normalize_company_name(name: str) -> str:
    s = name.lower()
    s = re.sub(r"\([^)]*\)", " ", s)
    s = s.replace("&", " and ")
    s = _COMPANY_SUFFIX_RE.sub(" ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _company_aliases(name: str) -> set[str]:
    aliases = {_normalize_company_name(name)}
    for part in re.findall(r"\(([^)]*)\)", name):
        aliases.add(_normalize_company_name(part))
    return {a for a in aliases if a}


def _company_name_matches(candidate: str, watchlist_name: str) -> bool:
    cand = _normalize_company_name(candidate)
    aliases = _company_aliases(watchlist_name)
    if not cand or not aliases:
        return False
    for watch in aliases:
        if cand == watch:
            return True
        # Allow LinkedIn variants like "MSCI Inc." vs "MSCI" or
        # "Amazon Web Services" vs "Amazon" without matching arbitrary substrings.
        if re.search(rf"(^|\s){re.escape(watch)}(\s|$)", cand):
            return True
    return False


def load_watchlist_companies() -> list[dict]:
    """Load company-watchlist rows from Notion, with a local cache fallback."""
    try:
        data = json.loads(notion_run("list-watchlist-companies"))
        WATCHLIST_CACHE_PATH.write_text(json.dumps({
            "updated_at": dt.datetime.now().isoformat(),
            "companies": data,
        }, indent=2))
        return data
    except Exception as e:
        if WATCHLIST_CACHE_PATH.exists():
            try:
                cached = json.loads(WATCHLIST_CACHE_PATH.read_text())
                return cached.get("companies", [])
            except Exception:
                pass
        print(f"WARNING: unable to load watchlist companies: {e}", file=sys.stderr)
        return []


def match_watchlist_company(company: str, watchlist: list[dict] | None = None) -> str | None:
    watchlist = watchlist if watchlist is not None else load_watchlist_companies()
    for row in watchlist:
        name = row.get("name") if isinstance(row, dict) else str(row)
        if name and _company_name_matches(company, name):
            return name
    return None


def _tailoring_reasons_for_company(company: str, watchlist: list[dict] | None = None) -> tuple[bool, str | None, list[str]]:
    match = match_watchlist_company(company, watchlist)
    reasons = ["watchlist_company"] if match else []
    return bool(match), match, reasons


_in_process_companies_cache: set[str] | None = None


def notion_in_process_companies() -> set[str]:
    """Company names from Notion rows currently in an active interview process.

    Fetched once per process run and cached. Falls back to an empty set so a
    Notion outage never blocks the apply run.
    """
    global _in_process_companies_cache
    if _in_process_companies_cache is not None:
        return _in_process_companies_cache
    companies: set[str] = set()
    for status in IN_PROCESS_STATUSES:
        try:
            data = json.loads(notion_run("list-by-status", status))
            for row in data:
                name = (row.get("company") or "").strip()
                if name:
                    companies.add(name)
        except Exception:
            pass
    _in_process_companies_cache = companies
    print(f"In-process companies: {sorted(companies)}", file=sys.stderr)
    return companies


def _is_blacklisted_company(company: str) -> bool:
    if any(_company_name_matches(company, blocked) for blocked in COMPANY_BLACKLIST):
        return True
    return any(_company_name_matches(company, blocked) for blocked in notion_in_process_companies())


def _ensure_tailoring_metadata(rc: dict, watchlist: list[dict] | None = None) -> tuple[dict, bool]:
    """Add watchlist-tailoring metadata to older role-context files."""
    if "requires_tailored_cv" in rc and "tailoring_required_reasons" in rc:
        return rc, False
    requires_tailored_cv, watchlist_match, tailoring_reasons = _tailoring_reasons_for_company(
        rc.get("company") or "",
        watchlist,
    )
    rc["watchlist_company"] = bool(watchlist_match)
    rc["watchlist_match"] = watchlist_match
    rc["requires_tailored_cv"] = requires_tailored_cv
    rc["tailoring_required_reasons"] = tailoring_reasons
    return rc, True


# ---------------------------------------------------------------------------
# search phase
# ---------------------------------------------------------------------------

# Named locations from search.locations in data/search_config.json. Each
# maps a shorthand key to (label, LinkedIn geo ID); geo IDs come from the
# geoId= parameter of a manual LinkedIn job search URL.
LOCATION_MAP: dict[str, tuple[str, str]] = {
    key: ((loc.get("label") or key), str(loc.get("linkedin_geo_id") or ""))
    for key, loc in (_SEARCH_CFG.get("locations") or {}).items()
}
for _loc_key, (_loc_label, _loc_geo) in LOCATION_MAP.items():
    if not _loc_geo:
        raise SystemExit(
            f"search.locations.{_loc_key}.linkedin_geo_id missing from "
            "data/search_config.json. Run /onboard or edit the file."
        )
_DEFAULT_LOCATIONS = ",".join(
    _SEARCH_CFG.get("default_locations") or list(LOCATION_MAP)
)

DATE_MAP = {
    "24h": "r86400",
    "week": "r604800",
    "month": "r2592000",
    "all": "",
}


# Named semantic-search queries from search.queries in data/search_config.json.
# LinkedIn's natural-language semantic search (post-2025 rollout) ranks by
# intent and surfaces title variants that exact keyword matching would miss.
# The classic /jobs/search/ endpoint accepts these multi-word queries when
# sortBy=R (Relevance) is set, AND keeps the standard
# `li[data-occludable-job-id]` markup that the scraper already understands.
# Calibration notes:
# - Keep each phrase below roughly 8 words; longer role-list queries collapse
#   onto the same broad retrieval cohort, defeating the point of having
#   multiple queries.
# - For infrequently-posted niches, drop the date filter (or use --date all);
#   the 24h/week filters can return only 1-2 results.
SEMANTIC_QUERIES: dict[str, str] = dict(_SEARCH_CFG.get("queries") or {})
_DEFAULT_QUERIES = ",".join(
    _SEARCH_CFG.get("default_queries") or list(SEMANTIC_QUERIES)
)


def build_search_urls(terms: list[str], locations: list[str], date_filter: str) -> list[tuple[str, str]]:
    """Build LinkedIn semantic-search URLs.

    `terms` are SEMANTIC_QUERIES keys (e.g. "finance", "applied",
    "engineering") OR a literal natural-language phrase. Each query is
    crossed with each location to produce one URL per (query, location).

    The URL uses sortBy=R (Relevance) so LinkedIn's semantic engine does
    the title-variant matching upstream. f_E is dropped because semantic
    ranking handles seniority intent more reliably than the experience
    facet, which often filters out legitimate matches with non-standard
    seniority labels in the title.
    """
    from urllib.parse import quote_plus
    out = []
    f_tpr = DATE_MAP.get(date_filter, "")
    for term in terms:
        query = SEMANTIC_QUERIES.get(term, term)
        for loc_key in locations:
            if loc_key not in LOCATION_MAP:
                continue
            label, geo = LOCATION_MAP[loc_key]
            url = (
                f"https://www.linkedin.com/jobs/search/?keywords={quote_plus(query)}"
                f"&location={quote_plus(label)}&geoId={geo}&sortBy=R"
            )
            if f_tpr:
                url += f"&f_TPR={f_tpr}"
            slug = f"{term}_{loc_key}"
            out.append((slug, url))
    return out


def scroll_results(target_min: int = 20, max_iter: int = 12) -> int:
    """Dynamic scroll loop matching the verified pattern in SKILL.md."""
    prev = -1
    stable = 0
    cnt = 0
    for _ in range(max_iter):
        raw = pcli_eval(
            """(() => {
              const card = document.querySelector('li[data-occludable-job-id]');
              if (!card) return -1;
              let el = card.parentElement;
              while (el) {
                const cs = getComputedStyle(el);
                if ((cs.overflowY === 'auto' || cs.overflowY === 'scroll')
                    && el.scrollHeight > el.clientHeight + 50) break;
                el = el.parentElement;
              }
              if (!el) return -2;
              el.scrollBy(0, 600);
              return document.querySelectorAll('li[data-occludable-job-id]').length;
            })()"""
        )
        try:
            cnt = int(raw) if raw is not None else 0
        except (TypeError, ValueError):
            cnt = 0
        if cnt == prev:
            stable += 1
            if stable >= 2 and cnt >= target_min:
                break
        else:
            stable = 0
            prev = cnt
        time.sleep(0.3)
    return int(cnt or 0)


def extract_cards() -> list[dict]:
    js = """(() => {
      const cards = document.querySelectorAll('li[data-occludable-job-id]');
      const dedupe = s => { if (!s) return ''; const half = Math.floor(s.length / 2);
        if (s.length > 10 && s.slice(0, half) === s.slice(half)) return s.slice(0, half);
        return s; };
      const out = [];
      cards.forEach(card => {
        const link = card.querySelector('a[href*="/jobs/view/"]');
        if (!link) return;
        const m = link.href.match(/\\/jobs\\/view\\/(\\d+)/);
        if (!m) return;
        const titleEl = card.querySelector('.job-card-list__title, a.job-card-container__link, [class*="job-card-container__link"]');
        const companyEl = card.querySelector('.artdeco-entity-lockup__subtitle, [class*="job-card-container__company-name"]');
        const locationEl = card.querySelector('.artdeco-entity-lockup__caption, [class*="job-card-container__metadata-item"], li[class*="metadata"]');
        out.push({
          id: m[1],
          title: dedupe(titleEl ? titleEl.textContent.trim().split('\\n')[0].trim() : ''),
          company: dedupe(companyEl ? companyEl.textContent.trim() : ''),
          location: locationEl ? locationEl.textContent.trim().split('(')[0].trim() : '',
          url: 'https://www.linkedin.com/jobs/view/' + m[1],
        });
      });
      return JSON.stringify(out);
    })()"""
    val = pcli_eval(js)
    if isinstance(val, list):
        return val
    return []


def fetch_jd_and_apply_type(job_id: str) -> dict:
    pcli("goto", f"https://www.linkedin.com/jobs/view/{job_id}/", timeout=30)
    time.sleep(2)
    # Expand collapsed JD / requirements sections before reading innerText.
    # LinkedIn collapses the "About the job" body and the "Requirements added
    # by the job poster" section behind a "…more" button. The expandable-text-box
    # button or any "See more" button inside the job details panel must be
    # clicked before innerText includes the full content.
    pcli_eval("""(() => {
      const btns = Array.from(document.querySelectorAll('button'));
      btns.forEach(b => {
        const label = (b.textContent || '').trim().toLowerCase();
        const inDetails = b.closest('[data-job-id], .jobs-details, .jobs-description, [class*="job-details"]');
        if (inDetails && (label.includes('more') || label === '…more' || label === '…')) {
          b.click();
        }
      });
    })()""")
    time.sleep(1)
    js = """(() => {
      let jd = '';
      const all = document.querySelectorAll('div, section, article');
      let best = null;
      all.forEach(el => {
        const t = el.innerText || '';
        if ((t.startsWith('About the job') || t.startsWith('About ')) && t.length > 500 && t.length < 15000) {
          if (!best || t.length > best.innerText.length) best = el;
        }
      });
      if (best) jd = best.innerText;
      let applyType = 'NONE';
      const easy = document.querySelector('a[aria-label*="LinkedIn Apply to this job"]');
      if (easy) {
        applyType = 'LINKEDIN_APPLY';
      } else {
        const ext = document.querySelector('a[aria-label*="Apply on company website"]');
        if (ext) {
          const m = (ext.href || '').match(/url=([^&]+)/);
          applyType = 'EXT:' + (m ? decodeURIComponent(m[1]) : ext.href);
        }
      }
      let company = '';
      const sel = document.querySelector('a[href*="/company/"][data-test-app-aware-link], .job-details-jobs-unified-top-card__company-name a, .topcard__org-name-link');
      if (sel) company = sel.textContent.trim();
      if (!company) {
        const cands = Array.from(document.querySelectorAll('a[href*="/company/"]'));
        if (cands.length) company = cands[0].textContent.trim();
      }
      return JSON.stringify({jd, applyType, company});
    })()"""
    val = pcli_eval(js)
    if not isinstance(val, dict):
        return {"jd": "", "applyType": "NONE", "company": ""}
    return val


def dismiss_card_on_linkedin(job_id: str) -> str:
    res = pcli_eval(
        f"""(() => {{
          const card = document.querySelector('li[data-occludable-job-id="{job_id}"]');
          if (!card) return 'card-not-found';
          const btn = card.querySelector('button[aria-label^="Dismiss "]');
          if (!btn) return 'dismiss-btn-not-found';
          btn.click();
          return 'clicked';
        }})()"""
    )
    time.sleep(0.4)
    return str(res)


def classify_apply_type(apply_type: str) -> tuple[str, str | None]:
    """Return (kind, host) where kind is one of:
        linkedin_apply | greenhouse | workday | lever | ashby
        | smartrecruiters | teamtailor | bamboohr | jobvite
        | not_automatable | unknown | none

    `not_automatable` is for ATSes / aggregators we know we can't drive
    deterministically and that have no useful escalation path either —
    e.g. Aplitrak (recruiter mailto-redirect aggregator). The orchestrator
    treats `not_automatable` like a hard fail rather than spinning up an
    edge-case agent that can't possibly succeed.
    """
    if apply_type == "LINKEDIN_APPLY":
        return ("linkedin_apply", None)
    if apply_type == "NONE":
        return ("none", None)
    if not apply_type.startswith("EXT:"):
        return ("unknown", None)
    url = apply_type[4:]
    host = (urlparse(url).hostname or "").lower()
    if host.endswith("greenhouse.io") or "grnh.se" in host or host.endswith("eu.greenhouse.io"):
        return ("greenhouse", host)
    if host.endswith("myworkdayjobs.com"):
        return ("workday", host)
    if host.endswith("lever.co"):
        return ("lever", host)
    if host.endswith("ashbyhq.com"):
        return ("ashby", host)
    if host.endswith("smartrecruiters.com"):
        return ("smartrecruiters", host)
    if host.endswith("teamtailor.com"):
        return ("teamtailor", host)
    if host.endswith("bamboohr.com"):
        return ("bamboohr", host)
    if host.endswith("jobvite.com"):
        return ("jobvite", host)
    if "welcometothejungle.com" in host:
        return ("wttj", host)
    # Known not-automatable aggregators
    if host.endswith("aplitrak.com") or host.endswith("appcast.io") or "adzuna" in host:
        return ("not_automatable", host)
    # Intelligence-based skip: hosts that have been tried many times and never succeeded.
    intel = _load_intelligence()
    skip_hosts = intel.get("skip_hosts", [])
    if host in skip_hosts:
        return ("not_automatable", host)
    # Pattern-based skip: ATS platforms that require account creation / CAPTCHA gates
    # and are never automatable (SuccessFactors, iCIMS, Avature, etc.).
    skip_patterns = intel.get("skip_host_patterns", [])
    if any(pattern in host for pattern in skip_patterns):
        return ("not_automatable", host)
    return ("unknown", host)


def cmd_search(args) -> int:
    if not LOCATION_MAP:
        print(
            "ERROR: search.locations is empty in data/search_config.json. "
            "Run /onboard or add at least one location.",
            file=sys.stderr,
        )
        return 2
    terms = [t.strip() for t in args.term.split(",") if t.strip()]
    locations = [l.strip() for l in args.location.split(",") if l.strip()]
    urls = build_search_urls(terms, locations, args.date)
    if not urls:
        print(
            "ERROR: no search URLs constructed. Check --term against "
            "search.queries and --location against search.locations in "
            "data/search_config.json.",
            file=sys.stderr,
        )
        return 2

    known = notion_known_linkedin_ids()
    print(f"Notion known IDs: {len(known)}", file=sys.stderr)
    watchlist_companies = load_watchlist_companies()
    print(f"Watchlist companies: {len(watchlist_companies)}", file=sys.stderr)

    submitted_today = count_today_linkedin_submissions()
    print(f"LinkedIn submissions today (rate-limit counter): {submitted_today}", file=sys.stderr)

    summary = {
        "scanned": 0,
        "title_skip": 0,
        "company_blacklist": 0,
        "duplicate": 0,
        "jd_empty": 0,
        "jd_external_review": 0,
        "visa_skip": 0,
        "jd_skip": 0,
        "apply": 0,
        "errors": 0,
    }
    apply_rows: list[dict] = []
    # Per-query cap ensures fair coverage across the (query x location)
    # URLs. A global max_roles would let one URL exhaust the whole budget.
    # Use a generous global ceiling as a safety bound.
    per_query = args.per_query or 5
    global_ceiling = (args.max_roles or 0) or (per_query * len(urls) + 50)

    for slug, url in urls:
        print(f"### URL {slug}: {url}", file=sys.stderr)
        try:
            pcli("goto", url, timeout=30)
            time.sleep(4)
            scroll_results()
            cards = extract_cards()
        except Exception as e:
            print(f"  search-failed {e}", file=sys.stderr)
            summary["errors"] += 1
            continue
        print(f"  cards={len(cards)}", file=sys.stderr)

        per_query_count = 0  # reset for each URL
        to_dismiss: list[str] = []  # IDs needing post-navigation dismissal
        for card in cards:
            summary["scanned"] += 1
            if per_query_count >= per_query:
                print(f"  per-query cap reached for {slug} ({per_query} APPLY)", file=sys.stderr)
                break
            if summary["apply"] >= global_ceiling:
                break
            jid = card["id"]
            title = card.get("title", "")
            company = card.get("company", "")
            location = card.get("location", "")

            if _is_blacklisted_company(company):
                summary["company_blacklist"] += 1
                dismiss_card_on_linkedin(jid)
                print(f"  {jid} COMPANY-BLACKLIST company={company[:30]}", file=sys.stderr)
                continue

            # title-only filter (threshold 0 = hard gates + title blacklist only)
            res = _qf.quick_filter(title, "", location, threshold=0)
            if res.get("verdict") != "APPLY":
                summary["title_skip"] += 1
                dismiss_card_on_linkedin(jid)
                continue

            if jid in known:
                summary["duplicate"] += 1
                dismiss_card_on_linkedin(jid)
                continue

            try:
                detail = fetch_jd_and_apply_type(jid)
            except Exception as e:
                print(f"  {jid} fetch-failed {e}", file=sys.stderr)
                summary["errors"] += 1
                continue
            jd = detail.get("jd", "") or ""
            apply_type = detail.get("applyType", "NONE")
            company = detail.get("company", "") or card.get("company", "")
            if _is_blacklisted_company(company):
                summary["company_blacklist"] += 1
                to_dismiss.append(jid)
                print(f"  {jid} COMPANY-BLACKLIST company={company[:30]}", file=sys.stderr)
                continue

            # Skip roles whose apply URL lands on a host that requires account
            # creation (SuccessFactors, iCIMS, Avature, etc.) — these are never
            # automatable and must not reach ReadyToApply.
            if apply_type.startswith("EXT:"):
                _ext_host = (urlparse(apply_type[4:]).hostname or "").lower()
                _kind_at_search, _ = classify_apply_type(apply_type)
                if _kind_at_search == "not_automatable":
                    summary["jd_skip"] += 1
                    to_dismiss.append(jid)
                    print(
                        f"  {jid} HOST-SKIP host={_ext_host} company={company[:30]}",
                        file=sys.stderr,
                    )
                    continue

            requires_tailored_cv, watchlist_match, tailoring_reasons = _tailoring_reasons_for_company(
                company,
                watchlist_companies,
            )

            if len(jd) < 50:
                if apply_type.startswith("EXT:"):
                    # Real JD lives on the external ATS. Add to Notion for
                    # manual review rather than silently discarding.
                    summary["jd_external_review"] += 1
                    _record_seen_ids([jid])
                    known.add(jid)
                    ext_country = guess_country(location)
                    try:
                        ext_result = create_notion_row(
                            title=title,
                            company=company,
                            location_label=country_to_notion_location(ext_country),
                            url=card["url"],
                            jd=f"JD not available on LinkedIn. Apply URL: {apply_type}",
                            notes=(
                                f"Auto-apply {dt.date.today().isoformat()}. "
                                f"ToReview: JD empty, external ATS. "
                                f"Apply: {apply_type[:60]}."
                            ),
                            status="ToReview",
                            salary=_extract_salary(title, ""),
                        )
                        ext_pid = ext_result.get("page_id")
                        if ext_pid:
                            ext_rc_dir = resolve_role_dir(jid, company)
                            ext_rc_dir.mkdir(parents=True, exist_ok=True)
                            (ext_rc_dir / "role-context.json").write_text(json.dumps({
                                "id": jid, "title": title, "company": company,
                                "location": location, "country": ext_country,
                                "url": card["url"], "apply_type": apply_type,
                                "variant": "general", "notion_page_id": ext_pid,
                                "watchlist_company": bool(watchlist_match),
                                "watchlist_match": watchlist_match,
                                "requires_tailored_cv": requires_tailored_cv,
                                "tailoring_required_reasons": tailoring_reasons,
                            }, indent=2))
                        print(f"  {jid} EXT-REVIEW company={company[:30]}", file=sys.stderr)
                    except Exception as e:
                        print(f"  {jid} ext-review-failed {e}", file=sys.stderr)
                else:
                    summary["jd_empty"] += 1
                    to_dismiss.append(jid)
                continue

            # Parse structured requirements and apply visa hard-skip for roles
            # in countries where sponsorship is needed.
            country = guess_country(location)
            requirements = _parse_requirements(jd)
            if _is_visa_hard_skip(requirements, country):
                summary["visa_skip"] += 1
                to_dismiss.append(jid)
                print(f"  {jid} VISA-SKIP company={company[:30]}", file=sys.stderr)
                continue

            jd_res = _qf.quick_filter(title, jd, location, threshold=5)
            if jd_res.get("verdict") != "APPLY":
                summary["jd_skip"] += 1
                to_dismiss.append(jid)
                continue

            # NOTE: Haiku realism check has been moved to cmd_prepare so that
            # the search phase has no LLM dependency and can run reliably every
            # day regardless of Claude API usage limits.

            # variant
            try:
                variant_info = _sv.select_variant(title=title, description=jd)
            except Exception as e:
                variant_info = {"variant": "general", "reason": f"select-failed: {e}"}
            variant = variant_info.get("variant") or "general"
            tailoring_note = (
                f" Requires tailored CV: watchlist company ({watchlist_match})."
                if watchlist_match else ""
            )

            # write per-role folder + JD + role-context.json
            rdir = resolve_role_dir(jid, company)
            rdir.mkdir(parents=True, exist_ok=True)
            (rdir / "jd.txt").write_text(jd)
            (rdir / "role-context.json").write_text(json.dumps({
                "id": jid,
                "title": title,
                "company": company,
                "location": location,
                "country": country,
                "url": card["url"],
                "apply_type": apply_type,
                "variant": variant,
                "watchlist_company": bool(watchlist_match),
                "watchlist_match": watchlist_match,
                "requires_tailored_cv": requires_tailored_cv,
                "tailoring_required_reasons": tailoring_reasons,
                "score": jd_res.get("competitiveness", {}),
                "requirements": requirements,
            }, indent=2))

            # write Notion row. Watchlist roles get NeedsTailoring (per-role
            # CV tailoring required). Non-watchlist roles are fast-tracked
            # straight to ReadyToApply using the variant template PDF — a
            # single employer-named copy is materialised in the role folder.
            initial_status = STATUS_NEEDS_TAILORING if requires_tailored_cv else STATUS_READY_TO_APPLY
            cv_url_for_notion: str | None = None
            if not requires_tailored_cv:
                template_pdf = CV_OUTPUT_DIR / f"{variant}.pdf"
                if not template_pdf.exists():
                    template_pdf = CV_OUTPUT_DIR / "general.pdf"
                if template_pdf.exists():
                    employer_cv = rdir / _employer_cv_filename({
                        "company": company, "title": title,
                    })
                    shutil.copyfile(template_pdf, employer_cv)
                    cv_url_for_notion = employer_cv.as_uri()
                else:
                    # No template available — fall back to NeedsTailoring so the
                    # role-tailorer agent can compile one from scratch.
                    initial_status = STATUS_NEEDS_TAILORING

            salary = _extract_salary(title, jd)
            fast_track_note = (
                "" if requires_tailored_cv
                else f" Fast-tracked to ReadyToApply with {variant} template (no watchlist match)."
            )
            try:
                notion_result = create_notion_row(
                    title=title,
                    company=company,
                    location_label=country_to_notion_location(country),
                    url=card["url"],
                    jd=jd,
                    notes=(
                        f"Auto-apply {dt.date.today().isoformat()}. "
                        f"Variant: {variant}. "
                        f"Apply: {apply_type[:40]}. "
                        f"Filter total: {jd_res.get('competitiveness', {}).get('total')}."
                        f"{tailoring_note}{fast_track_note}"
                    ),
                    status=initial_status,
                    salary=salary,
                )
                notion_page_id = notion_result.get("page_id")
                if notion_page_id:
                    rc = json.loads((rdir / "role-context.json").read_text())
                    rc["notion_page_id"] = notion_page_id
                    (rdir / "role-context.json").write_text(json.dumps(rc, indent=2))
                    if cv_url_for_notion:
                        try:
                            notion_run("set-artefacts", notion_page_id, f"--cv={cv_url_for_notion}")
                        except Exception as e:
                            print(f"  {jid} cv-artefact-write-failed {e}", file=sys.stderr)
            except Exception as e:
                print(f"  {jid} notion-write-failed {e}", file=sys.stderr)
                summary["errors"] += 1
                continue

            known.add(jid)
            summary["apply"] += 1
            per_query_count += 1
            apply_rows.append({
                "id": jid,
                "title": title,
                "company": company,
                "apply_type": apply_type,
                "variant": variant,
                "requires_tailored_cv": requires_tailored_cv,
                "watchlist_match": watchlist_match,
            })
            print(f"  {jid} APPLY company={company[:30]} variant={variant}", file=sys.stderr)

        # Batch dismiss jd_empty + jd_skip cards. These were accumulated after
        # navigating to job detail pages so they can't be dismissed inline.
        # Navigate back to the search URL, attempt dismissal for each ID,
        # and cache all IDs locally so they are caught as duplicates next run
        # (at the pre-navigation duplicate check, where dismissal is reliable).
        if to_dismiss:
            _record_seen_ids(to_dismiss)
            try:
                pcli("goto", url, timeout=20)
                time.sleep(3)
                clicked = sum(
                    1 for jid in to_dismiss
                    if dismiss_card_on_linkedin(jid) == "clicked"
                )
                print(
                    f"  post-nav dismiss: {clicked}/{len(to_dismiss)} clicked"
                    f" (rest scrolled off DOM — cached for next run)",
                    file=sys.stderr,
                )
            except Exception as e:
                print(
                    f"  post-nav dismiss failed ({e})"
                    f" — {len(to_dismiss)} IDs cached for next run",
                    file=sys.stderr,
                )

        if summary["apply"] >= global_ceiling:
            print(f"global ceiling reached ({global_ceiling})", file=sys.stderr)
            break

    # write run artefact
    run_dir = RUNS_DIR / dt.date.today().isoformat()
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "search-summary.json").write_text(json.dumps({
        "summary": summary,
        "apply_rows": apply_rows,
        "ts": dt.datetime.now().isoformat(),
        "args": {k: v for k, v in vars(args).items() if k != "func"},
    }, indent=2))

    print(json.dumps({"summary": summary, "apply_rows": apply_rows}, indent=2))
    return 0


# ---------------------------------------------------------------------------
# helpers used across phases
# ---------------------------------------------------------------------------

def guess_country(location: str) -> str:
    s = location.lower()
    if "united kingdom" in s or "london" in s or "england" in s or "scotland" in s:
        return "United Kingdom"
    if "france" in s or "paris" in s or "île-de-france" in s or "ile-de-france" in s:
        return "France"
    if "switzerland" in s or "zurich" in s or "geneva" in s or "lausanne" in s:
        return "Switzerland"
    if "canada" in s or "toronto" in s or "montreal" in s:
        return "Canada"
    if "japan" in s or "tokyo" in s:
        return "Japan"
    if "remote" in s or "emea" in s or "european union" in s:
        return "Unknown"
    return "Unknown"


def country_to_notion_location(country: str) -> str:
    """Notion `Location` is a Select field. Map countries to the Select
    labels configured in notion.location_labels in data/search_config.json;
    anything unmapped falls back to "Other"."""
    table = _CONFIG.get("notion", {}).get("location_labels") or {}
    return table.get(country, "Other")


def count_today_linkedin_submissions() -> int:
    """Count submission-log.json files written today where submitted_via
    matches the current or legacy LinkedIn Apply string (per skill spec)."""
    today = dt.date.today().isoformat()
    n = 0
    paths = list(APPLICATIONS_DIR.glob("*/submission-log.json")) + list(
        APPLICATIONS_DIR.glob("*/*/submission-log.json")
    )
    for p in paths:
        try:
            d = json.loads(p.read_text())
        except Exception:
            continue
        sv = d.get("submitted_via") or ""
        if "LinkedIn Apply" not in sv:
            continue
        ts = d.get("submitted_at", "")
        if ts.startswith(today):
            n += 1
    return n


# (?!\d) pins the digit match so the engine cannot backtrack to a partial number
# (e.g. avoid matching "$17" from "$170M" by backtracking off the "0").
# \b after the multiplier keyword ensures "base" or "billion" in a word like
# "database" or "assemblage" does not trigger a false rejection.
_NO_DIGIT_AHEAD = r"(?!\d)"
_NO_MULTIPLIER_AHEAD = r"(?!\s*(?:M|B|Bn|bn|[Mm]illion|[Bb]illion)\b)"
_EXCL = _NO_DIGIT_AHEAD + _NO_MULTIPLIER_AHEAD

_AMOUNT_UNIT = r"[£€\$]\s*[\d,]+(?:k|,000)?" + _EXCL
_RANGE_TAIL = r"(?:\s*[-–]\s*[£€\$]?\s*[\d,]+(?:k|,000)?" + _EXCL + r")?"
_BONUS_TAIL = r"(?:\s*\+[^.\n]{0,50})?"

# Full pattern: any currency amount not followed by a multiplier word.
_SALARY_FULL_RE = re.compile(
    _AMOUNT_UNIT + _RANGE_TAIL + _BONUS_TAIL,
    re.IGNORECASE,
)

# Structural pattern: only comma-formatted (£60,000) or k-suffixed (£85k).
# Bare numbers like $170 or £7 are structurally excluded here even without
# multiplier context, acting as a last-resort filter.
_SALARY_STRUCTURED_RE = re.compile(
    r"[£€\$]\s*(?:\d{1,3}(?:,\d{3})+|\d+k)" + _EXCL + _RANGE_TAIL + _BONUS_TAIL,
    re.IGNORECASE,
)

# Keywords that signal a salary is being stated nearby in the JD.
_SALARY_KW_RE = re.compile(
    r"(?:salary|salaire|compensation|r[eé]mun[eé]ration|package|"
    r"per\s+annum|p\.?a\.?|annual(?:ly)?|OTE|on.?target|"
    r"base\s+pay|total\s+comp(?:ensation)?|earnings?|wage)",
    re.IGNORECASE,
)


def _extract_salary(title: str, jd: str) -> str | None:
    """Extract a salary or salary range from the job title or JD.

    Three-stage search — returns None rather than a false positive:
      1. Title scan: any currency amount not followed by M/B/bn.
      2. Keyword-context scan: currency within 200 chars of a salary keyword in the JD.
      3. Structural fallback: comma-formatted (£60,000) or k-suffixed (£85k) amounts
         anywhere in the first 4000 chars of the JD.
    """
    # Stage 1: title (most reliable — tightly formatted by the job poster)
    m = _SALARY_FULL_RE.search(title)
    if m:
        return m.group(0).strip()

    jd_head = jd[:4000]

    # Stage 2: currency near a salary keyword
    for kw in _SALARY_KW_RE.finditer(jd_head):
        window = jd_head[max(0, kw.start() - 200): kw.end() + 200]
        m = _SALARY_FULL_RE.search(window)
        if m:
            return m.group(0).strip()

    # Stage 3: structural fallback — comma-formatted or k-suffixed only
    m = _SALARY_STRUCTURED_RE.search(jd_head)
    if m:
        return m.group(0).strip()

    return None


_REQUIREMENTS_HEADER = "Requirements added by the job poster"

# Patterns that indicate visa/right-to-work requirements the candidate cannot meet.
# Applies only to roles where sponsorship is needed (France, EU, etc.).
_VISA_SKIP_RE = re.compile(
    r"no\s+(need\s+for\s+)?visa\s+sponsor"       # "No need for visa sponsorship"
    r"|must\s+(be\s+)?(legally\s+)?(authori[sz]ed|eligible)\s+to\s+work"
    r"|right\s+to\s+work\s+in"
    r"|work\s+authori[sz]ation\s+required"
    r"|EU\s+(citizen|national)"
    r"|European?\s+(citizen|national)"
    r"|no\s+sponsorship",
    re.IGNORECASE,
)

# Countries where the candidate needs sponsorship: a visa hard-skip check
# applies there. Home countries (right to work already held) never trigger
# the check. Both sets come from data/search_config.json.
_SPONSORSHIP_NEEDED = set(_CANDIDATE_CFG.get("needs_sponsorship_in") or [])
_HOME_COUNTRIES = set(_CANDIDATE_CFG.get("home_countries") or [])


def _parse_requirements(jd: str) -> list[str]:
    """Extract bullet points from the 'Requirements added by the job poster'
    section, if present. Returns an empty list when the section is absent."""
    if _REQUIREMENTS_HEADER not in jd:
        return []
    section = jd[jd.index(_REQUIREMENTS_HEADER) + len(_REQUIREMENTS_HEADER):]
    bullets = re.findall(r"[•·\-\*]\s*(.+)", section)
    return [b.strip() for b in bullets if b.strip()]


def _is_visa_hard_skip(requirements: list[str], country: str) -> bool:
    """Return True when the job poster's requirements contain an explicit
    right-to-work or no-sponsorship clause that this candidate cannot satisfy.
    Only applies to countries where sponsorship is required."""
    if country in _HOME_COUNTRIES:
        return False
    if not requirements or country not in _SPONSORSHIP_NEEDED:
        return False
    return any(_VISA_SKIP_RE.search(r) for r in requirements)


def create_notion_row(*, title: str, company: str, location_label: str,
                       url: str, jd: str, notes: str, status: str,
                       salary: str | None = None) -> dict:
    """Create a Notion row via notion_cli.py create-job. Returns the parsed
    JSON response including page_id — caller should cache page_id immediately."""
    payload = {
        "title": title,
        "company": company,
        "location": location_label,
        "url": url,
        "status": status,
        "description": jd,
        "notes": notes,
        "source": "LinkedIn",
    }
    if salary:
        payload["salary"] = salary
    out = notion_run("create-job", "--payload", json.dumps(payload))
    return json.loads(out) if out.strip() else {}


# ---------------------------------------------------------------------------
# session lifecycle
# ---------------------------------------------------------------------------

def cmd_session_open(args) -> int:
    if not LINKEDIN_STATE.exists():
        print(
            "ERROR: data/.linkedin-state.json missing. "
            "Run `python scripts/save_linkedin_state.py` first.",
            file=sys.stderr,
        )
        return 2
    # close any stale session
    subprocess.run(["playwright-cli", f"-s={SESSION_NAME}", "close"],
                    capture_output=True, text=True)
    pcli("open")
    pcli("state-load", str(LINKEDIN_STATE))
    pcli("goto", "https://www.linkedin.com/feed/", timeout=30)
    time.sleep(3)
    state = pcli_eval(
        "(() => ({url: location.href, hasSignIn: !!document.querySelector('a[href*=\"/login\"]')}))()"
    )
    if not isinstance(state, dict) or state.get("hasSignIn"):
        print("ERROR: LinkedIn auth expired. Re-run save_linkedin_state.py.", file=sys.stderr)
        return 2
    # dismiss the cookie banner if present
    pcli_eval(
        """(() => {
          const reject = document.querySelector('button[action-type="DENY"], button[data-control-name="ga-cookie.consent.deny.v4"]');
          if (reject) { reject.click(); return 'rejected'; }
          // remove the interop-outlet shadow if it intercepts pointer events
          const outlet = document.querySelector('#interop-outlet');
          if (outlet) { outlet.remove(); return 'removed-interop-outlet'; }
          return 'no-action';
        })()"""
    )
    print("session-open: OK")
    return 0


def cmd_session_close(args) -> int:
    pcli("close")
    print("session-close: OK")
    return 0


# ---------------------------------------------------------------------------
# list-queue / status transitions
# ---------------------------------------------------------------------------

def cmd_list_queue(args) -> int:
    out = notion_run("list-by-status", args.status)
    data = json.loads(out)
    rows = []
    watchlist_companies = load_watchlist_companies()
    for j in data:
        url = j.get("url") or ""
        m = re.search(r"/jobs/view/(\d+)", url)
        watchlist_match = match_watchlist_company(j.get("company") or "", watchlist_companies)
        rows.append({
            "id": m.group(1) if m else None,
            "page_id": j.get("page_id") or j.get("id"),
            "title": j.get("title"),
            "company": j.get("company"),
            "url": url,
            "requires_tailored_cv": bool(watchlist_match),
            "watchlist_match": watchlist_match,
        })
    limit = getattr(args, "limit", 0) or 0
    if limit > 0:
        rows = rows[:limit]
    print(json.dumps(rows, indent=2))
    return 0


def _slugify(text: str, max_len: int = 30) -> str:
    """Convert free text to a safe lowercase slug for filenames."""
    slug = re.sub(r"[^\w\s-]", "", text).strip()
    slug = re.sub(r"[\s_]+", "-", slug).lower()
    return slug[:max_len].rstrip("-")


def _safe_cv_filename_part(text: str, max_len: int) -> str:
    """Keep employer-facing CV filenames professional and filesystem-safe."""
    ascii_text = (text or "").encode("ascii", "ignore").decode("ascii")
    part = re.sub(r"[^A-Za-z0-9 &.,+()'-]", " ", ascii_text)
    part = re.sub(r"\s+", " ", part).strip(" .-_")
    return part[:max_len].rstrip(" .-_")


def _employer_cv_filename(rc: dict | None = None) -> str:
    rc = rc or {}
    company = _safe_cv_filename_part(rc.get("company") or "", max_len=48)
    role = _safe_cv_filename_part(rc.get("title") or "", max_len=80)
    suffix = " ".join(part for part in (company, role) if part)
    if not suffix:
        return EMPLOYER_CV_NAME
    return f"{EMPLOYER_CV_BASENAME} - {suffix}.pdf"


def _employer_cv_candidates(role_dir: Path, rc: dict | None = None) -> list[Path]:
    candidates = [role_dir / _employer_cv_filename(rc), role_dir / EMPLOYER_CV_NAME]
    candidates.extend(sorted(role_dir.glob(f"{EMPLOYER_CV_BASENAME}*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True))
    out: list[Path] = []
    seen: set[Path] = set()
    for path in candidates:
        if path not in seen:
            seen.add(path)
            out.append(path)
    return out


def _ensure_employer_cv_file(rid: str, rc: dict | None = None) -> Path:
    role_dir = resolve_role_dir(rid)
    dest = role_dir / _employer_cv_filename(rc)
    if dest.exists():
        return dest
    for existing in _employer_cv_candidates(role_dir, rc):
        if existing.exists():
            shutil.copyfile(existing, dest)
            return dest
    for source in (role_dir / "cv.pdf", role_dir / "cv-template-fallback.pdf"):
        if source.exists():
            shutil.copyfile(source, dest)
            return dest
    return dest


def cmd_mark_ready(args) -> int:
    """Mark a role ReadyToApply. Renames the tailored cv.pdf to the
    employer-facing filename ('<employer_filename_base> - <company> <role>.pdf')
    and writes that file:// URL to Notion's Tailored CV field. A single PDF
    lives in the role folder; no audit copy."""
    rid = args.role
    role_dir = resolve_role_dir(rid)
    rc_path = role_dir / "role-context.json"
    if not rc_path.exists():
        print(f"ERROR: role-context.json missing for {rid}", file=sys.stderr)
        return 2
    rc = json.loads(rc_path.read_text())
    rc, changed = _ensure_tailoring_metadata(rc)
    if changed:
        rc_path.write_text(json.dumps(rc, indent=2))

    # Resolve the tailored CV: prefer employer-named file, then cv.pdf
    # (legacy build artefact name), then template fallback.
    employer_cv = role_dir / _employer_cv_filename(rc)
    cv_src = None
    if employer_cv.exists():
        cv_src = employer_cv
    elif (role_dir / "cv.pdf").exists():
        cv_src = role_dir / "cv.pdf"

    if rc.get("requires_tailored_cv") and cv_src is None:
        reasons = ", ".join(rc.get("tailoring_required_reasons") or ["watchlist_company"])
        print(
            f"ERROR: {rid} requires a tailored CV ({reasons}); "
            f"write {employer_cv} before mark-ready.",
            file=sys.stderr,
        )
        return 2
    if cv_src is None:
        cv_src = role_dir / "cv-template-fallback.pdf"

    # Rename to the employer-facing filename if not already there.
    if cv_src.resolve() != employer_cv.resolve():
        shutil.move(str(cv_src), str(employer_cv))
    # Clean up legacy cv.pdf if the employer-named file now exists
    legacy = role_dir / "cv.pdf"
    if legacy.exists() and legacy.resolve() != employer_cv.resolve():
        legacy.unlink()

    # Update Notion: set status + write Tailored CV URL pointing at the
    # employer-facing file in the role folder.
    page_id = resolve_page_id(rid)
    notion_run("update-status", page_id, STATUS_READY_TO_APPLY)
    notion_run("set-artefacts", page_id, f"--cv={employer_cv.as_uri()}")

    print(f"mark-status {rid} -> ReadyToApply: OK")
    print(f"  cv : {employer_cv}")
    return 0


def _write_manual_apply_md(rid: str, reason: str) -> None:
    """Write a MANUAL-APPLY.md cheat sheet into the application folder."""
    role_dir = resolve_role_dir(rid)
    if not role_dir.exists():
        return

    rc_path = role_dir / "role-context.json"
    rc = json.loads(rc_path.read_text()) if rc_path.exists() else {}

    profile_path = ROOT / "data" / "application_profile.json"
    if not profile_path.exists():
        raise RuntimeError(
            "data/application_profile.json not found. Run /onboard to create "
            "it before MANUAL-APPLY.md cheat sheets can be written."
        )
    profile = json.loads(profile_path.read_text())
    identity = profile.get("identity", {})
    auth = profile.get("citizenship_and_authorisation", {})
    avail = profile.get("availability", {})
    comp = profile.get("compensation", {})

    def _req_identity(key: str) -> str:
        """Required identity field; no personal fallbacks are permitted."""
        val = str(identity.get(key) or "").strip()
        if not val:
            raise RuntimeError(
                f"identity.{key} missing from data/application_profile.json. "
                "Run /onboard to populate it."
            )
        return val

    first_name = _req_identity("first_name")
    last_name = _req_identity("last_name")
    full_name = str(identity.get("full_name") or f"{first_name} {last_name}").strip()
    email = _req_identity("email")
    phone = _req_identity("phone")

    cv_path = _resolve_cv_path(rid)
    tex_files = list(role_dir.glob("*.tex"))
    tex_name = tex_files[0].name if tex_files else None

    # Plain-English description of the blocker and what to do
    blocker_hints = [
        ("lever-hcaptcha", "Form fully filled by automation — just solve the hCaptcha and click Submit."),
        ("hcaptcha", "hCaptcha required — solve it and click Submit."),
        ("recaptcha", "reCAPTCHA required — solve it and click Submit."),
        ("ashby-spam", "Ashby anti-bot detected automation. Re-fill manually (all fields are standard)."),
        ("greenhouse-required-fields", "Greenhouse form — unfilled required fields listed in reason. Fill and submit."),
        ("greenhouse-email-verification", "Greenhouse — email verification code required."),
        ("workday-account-creation", "Workday — account creation required before applying."),
        ("taleo", "Taleo — requires an account. Create one, then apply."),
        ("wttj-external-ats-redirect", "WTTJ listing redirected to an external ATS — check payload.target_ats and re-dispatch with the resolved URL."),
        ("wttj-login-required", "WTTJ requires a candidate account sign-in before the form. Log in and re-apply manually."),
        ("wttj-cover-letter-required", "WTTJ form requires a cover letter — edge-case agent must compose it."),
        ("wttj-required-fields", "WTTJ form has unfilled required fields listed in payload. Fill and submit."),
        ("unknown-ats", "Unknown ATS — navigate to the URL and apply directly."),
        ("needs_human", "Screening question the automation could not answer — see reason for the question text."),
        ("linkedin-session", "LinkedIn session expired — run save_linkedin_state.py, then re-apply via drain-queue."),
    ]
    blocker_desc = "See escalation reason above for details."
    for key, hint in blocker_hints:
        if key in reason:
            blocker_desc = hint
            break

    url = rc.get("url", f"https://www.linkedin.com/jobs/view/{rid}")
    company = rc.get("company", "")
    title = rc.get("title", rid)
    country = rc.get("country", "Unknown")

    # Work-authorisation status for this country: prefer the explicit
    # per-country entry in application_profile.json, then fall back to the
    # home-country / sponsorship sets in data/search_config.json.
    by_country = auth.get("by_country", {})
    auth_info = by_country.get(country) or {}
    authorised = auth_info.get("authorised_to_work", country in _HOME_COUNTRIES)
    needs_sponsorship = auth_info.get(
        "requires_sponsorship_now", country in _SPONSORSHIP_NEEDED
    )

    default_salary = comp.get("default_target") or comp.get("default_target_gbp")
    currency = str(comp.get("currency_symbol") or comp.get("currency") or "").strip()
    if isinstance(default_salary, (int, float)):
        salary_text = f"{currency}{default_salary:,.0f} (adjust to JD range if stated)"
    else:
        salary_text = (
            "Not set; add compensation.default_target to "
            "data/application_profile.json"
        )

    lines = [
        f"# {title}",
        f"## {company}",
        "",
        f"**Escalation reason:** `{reason}`",
        f"**What to do:** {blocker_desc}",
        "",
        "---",
        "",
        f"**Application URL:** {url}",
        f"**CV file:** `{cv_path.name}`",
    ]
    if tex_name:
        lines.append(f"**LaTeX source:** `{tex_name}`  (edit and recompile if CV needs fixing)")
    lines += [
        "",
        "---",
        "",
        "## Standard answers (copy-paste ready)",
        "",
        f"| Field | Value |",
        f"|-------|-------|",
        f"| First name | {first_name} |",
        f"| Last name | {last_name} |",
        f"| Full name | {full_name} |",
        f"| Email | {email} |",
        f"| Phone | {phone} |",
        f"| LinkedIn | {identity.get('linkedin_url', '')} |",
        f"| GitHub | {identity.get('github_url', '')} |",
        f"| Address | {identity.get('address_line_1', '')}, {identity.get('city', '')}, {identity.get('postcode', '')} |",
        f"| Right to work | {'Yes' if authorised else 'Requires sponsorship'} |",
        f"| Sponsorship needed | {'No' if not needs_sponsorship else 'Yes'} |",
        f"| Notice period | {avail.get('notice_period_text', 'Available immediately')} |",
        f"| Salary expectation | {salary_text} |",
        f"| Preferred pronouns | {identity.get('pronouns') or 'Prefer not to say'} |",
        "",
        "## Optional / diversity fields",
        "",
        "Demographic questions default to 'Prefer not to say' unless a value",
        "is explicitly set in application_profile.json. Never guess these.",
        "",
        "| Field | Value |",
        "|-------|-------|",
        f"| Gender | {identity.get('gender') or 'Prefer not to say'} |",
        f"| Ethnicity | {identity.get('ethnicity') or 'Prefer not to say'} |",
        f"| Disability | {identity.get('disability') or 'Prefer not to say'} |",
        f"| Veteran status | {identity.get('veteran_status') or 'Prefer not to say'} |",
    ]

    # If the AI screening layer generated a draft, show it as a suggestion
    # so the human reviewer can accept or adjust rather than start from scratch.
    ai_log_path = role_dir / "ai-screening-log.json"
    if ai_log_path.exists():
        try:
            ai_entries = json.loads(ai_log_path.read_text())
            if isinstance(ai_entries, list):
                ai_suggestions = [
                    e for e in ai_entries
                    if not e.get("auto_filled") and e.get("drafter_response")
                ]
                if ai_suggestions:
                    lines += [
                        "",
                        "---",
                        "",
                        "## AI-drafted answers (review before submitting)",
                        "",
                        "These answers were generated by the AI screening layer but "
                        "were not auto-filled (informational mode or reviewer rejected). "
                        "Review each carefully against your profile before using.",
                        "",
                    ]
                    for entry in ai_suggestions:
                        q_label = entry.get("label", "Unknown question")
                        dr = entry.get("drafter_response") or {}
                        rv = entry.get("reviewer_response") or {}
                        suggested = rv.get("revised_answer") or dr.get("answer") or "(no answer generated)"
                        category = dr.get("category", "")
                        rationale = dr.get("rationale", "")
                        verdict = rv.get("verdict", "")
                        reason = rv.get("reason", "")
                        flags = rv.get("red_flags") or []
                        lines += [
                            f"### {q_label}",
                            f"- **Category:** {category}",
                            f"- **AI suggested answer:** {suggested}",
                            f"- **Rationale:** {rationale}",
                        ]
                        if verdict:
                            lines.append(f"- **Reviewer verdict:** {verdict} — {reason}")
                        if flags:
                            lines.append(f"- **Red flags:** {', '.join(flags)}")
                        lines.append("")
        except (json.JSONDecodeError, OSError):
            pass

    (role_dir / "MANUAL-APPLY.md").write_text("\n".join(lines) + "\n")


def cmd_mark_status(args, status: str, extra_notes: str = "") -> int:
    """Set Notion Status by Notion page_id (resolved from LinkedIn ID).
    notion_cli interface is positional: `update-status <page> <status>`.
    Notes are appended via the separate `append-notes` subcommand."""
    page_id = resolve_page_id(args.role)
    notion_run("update-status", page_id, status)
    if extra_notes:
        notion_run("append-notes", page_id, extra_notes)
    if status == STATUS_ESCALATED:
        try:
            _write_manual_apply_md(args.role, extra_notes)
        except Exception as e:
            # The status transition itself succeeded; surface the cheat-sheet
            # failure (usually missing profile fields) without failing the run.
            print(f"WARNING: could not write MANUAL-APPLY.md: {e}", file=sys.stderr)
    print(f"mark-status {args.role} -> {status}: OK")
    return 0


def resolve_page_id(linkedin_id: str) -> str:
    """Find the Notion page_id for a LinkedIn job ID by scanning likely
    statuses. Cached on applications/<id>/role-context.json once
    resolved."""
    rc_path = resolve_role_dir(linkedin_id) / "role-context.json"
    if rc_path.exists():
        rc = json.loads(rc_path.read_text())
        if rc.get("notion_page_id"):
            return rc["notion_page_id"]
    # Search the v2 active statuses first (most likely match for an
    # in-flight role), then fall back to the rest.
    likely = (STATUS_NEEDS_TAILORING, STATUS_READY_TO_APPLY,
              STATUS_AWAITING_RESPONSE, STATUS_ESCALATED, STATUS_FAILED)
    rest = tuple(s for s in KNOWN_NOTION_STATUSES if s not in likely)
    for status in (*likely, *rest):
        try:
            data = json.loads(notion_run("list-by-status", status))
        except Exception:
            continue
        for j in data:
            if linkedin_id in (j.get("url") or ""):
                pid = j.get("page_id") or j.get("id")
                if rc_path.exists():
                    rc = json.loads(rc_path.read_text())
                    rc["notion_page_id"] = pid
                    rc_path.write_text(json.dumps(rc, indent=2))
                return pid
    raise RuntimeError(f"Notion page not found for LinkedIn ID {linkedin_id}")


# ---------------------------------------------------------------------------
# prepare (per-role folder + variant + template fallback)
# ---------------------------------------------------------------------------

def _read_prepare_jd_override(args) -> str:
    """Return JD text passed explicitly to `prepare`, if any."""
    jd_text = (getattr(args, "jd_text", None) or "").strip()
    jd_file = getattr(args, "jd_file", None)
    if jd_text and jd_file:
        raise ValueError("Use either --jd-text or --jd-file, not both")
    if jd_text:
        return jd_text
    if jd_file:
        return Path(jd_file).read_text().strip()
    return ""


def _hydrate_role_from_notion(rid: str, jd_override: str = "") -> tuple[dict, str]:
    """Create the local per-role files for a Notion-queued role.

    Current `search` runs already write applications/<id>/ before adding
    the row to Notion. Older imports/watchlist rows can exist in Notion without
    those local artefacts, so `prepare` needs a controlled hydration path.
    """
    page_id = resolve_page_id(rid)
    job = json.loads(notion_run("get-job", page_id))
    url = job.get("url") or f"https://www.linkedin.com/jobs/view/{rid}"
    title = job.get("title") or ""
    company = job.get("company") or ""
    location = job.get("location") or ""
    notes = job.get("notes") or ""
    jd = jd_override or (job.get("description") or "").strip()
    country = guess_country(location)
    requires_tailored_cv, watchlist_match, tailoring_reasons = _tailoring_reasons_for_company(company)

    try:
        variant_info = _sv.select_variant(title=title, description=jd or notes)
    except Exception as e:
        variant_info = {"variant": "general", "reason": f"select-failed: {e}"}

    rc = {
        "id": rid,
        "title": title,
        "company": company,
        "location": location,
        "country": country,
        "url": url,
        "apply_type": "NONE",
        "variant": variant_info.get("variant") or "general",
        "watchlist_company": bool(watchlist_match),
        "watchlist_match": watchlist_match,
        "requires_tailored_cv": requires_tailored_cv,
        "tailoring_required_reasons": tailoring_reasons,
        "score": {},
        "requirements": _parse_requirements(jd) if jd else [],
        "notion_page_id": page_id,
        "hydrated_from_notion": True,
    }
    return rc, jd


def cmd_prepare(args) -> int:
    rid = args.role
    role_dir = resolve_role_dir(rid)
    rc_path = role_dir / "role-context.json"
    try:
        jd_override = _read_prepare_jd_override(args)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    if not rc_path.exists():
        try:
            rc, jd = _hydrate_role_from_notion(rid, jd_override=jd_override)
        except Exception as e:
            print(
                f"ERROR: role-context.json missing for {rid} and Notion hydration failed: {e}",
                file=sys.stderr,
            )
            return 2
        role_dir.mkdir(parents=True, exist_ok=True)
        rc_path.write_text(json.dumps(rc, indent=2))
        if jd:
            (role_dir / "jd.txt").write_text(jd)
    else:
        role_dir.mkdir(parents=True, exist_ok=True)
        if jd_override:
            (role_dir / "jd.txt").write_text(jd_override)
            rc = json.loads(rc_path.read_text())
            rc, _ = _ensure_tailoring_metadata(rc)
            rc["requirements"] = _parse_requirements(jd_override)
            try:
                variant_info = _sv.select_variant(
                    title=rc.get("title") or "",
                    description=jd_override,
                )
                rc["variant"] = variant_info.get("variant") or rc.get("variant") or "general"
            except Exception:
                rc["variant"] = rc.get("variant") or "general"
            rc_path.write_text(json.dumps(rc, indent=2))
        else:
            jd_path = role_dir / "jd.txt"
            if not jd_path.exists() or not jd_path.read_text().strip():
                try:
                    page_id = resolve_page_id(rid)
                    job = json.loads(notion_run("get-job", page_id))
                    notion_jd = (job.get("description") or "").strip()
                except Exception:
                    notion_jd = ""
                if notion_jd:
                    jd_path.write_text(notion_jd)
                    rc = json.loads(rc_path.read_text())
                    rc, _ = _ensure_tailoring_metadata(rc)
                    rc["requirements"] = _parse_requirements(notion_jd)
                    try:
                        variant_info = _sv.select_variant(
                            title=rc.get("title") or "",
                            description=notion_jd,
                        )
                        rc["variant"] = variant_info.get("variant") or rc.get("variant") or "general"
                    except Exception:
                        rc["variant"] = rc.get("variant") or "general"
                    rc_path.write_text(json.dumps(rc, indent=2))

    jd_path = role_dir / "jd.txt"
    if not jd_path.exists() or not jd_path.read_text().strip():
        print(
            "ERROR: JD missing for "
            f"{rid}. The Notion row has no Job Description, so prepare "
            "cannot create a useful tailoring input. Re-run with "
            "--jd-file <path> or --jd-text '<job description>'.",
            file=sys.stderr,
        )
        return 2

    rc = json.loads(rc_path.read_text())
    rc, changed = _ensure_tailoring_metadata(rc)
    if changed:
        rc_path.write_text(json.dumps(rc, indent=2))

    # Haiku realism check (moved from search phase so search has no LLM
    # dependency and can run reliably every day regardless of Claude API limits).
    # Runs here instead so the JD is always available and confirmed non-empty.
    jd_for_check = jd_path.read_text()
    realistic, realism_reason = _haiku_realism_check(rc.get("title") or "", jd_for_check)
    if not realistic:
        print(f"HAIKU-SKIP {rid} reason={realism_reason!r}", file=sys.stderr)
        try:
            page_id = resolve_page_id(rid)
            notion_run("update-status", page_id, STATUS_SKIP)
            notion_run(
                "append-notes",
                page_id,
                f"Haiku-filtered {dt.date.today().isoformat()}: {realism_reason}",
            )
        except Exception as e:
            print(f"  notion-update-failed {e}", file=sys.stderr)
        print(json.dumps({
            "role": rid,
            "haiku_skip": True,
            "haiku_reason": realism_reason,
        }))
        return 3

    variant = rc.get("variant") or "general"
    template_pdf = ROOT / "cv" / "output" / f"{variant}.pdf"
    if not template_pdf.exists():
        template_pdf = ROOT / "cv" / "output" / "general.pdf"
    fallback = role_dir / "cv-template-fallback.pdf"
    shutil.copyfile(template_pdf, fallback)
    print(json.dumps({
        "role": rid,
        "variant": variant,
        "template_pdf": str(template_pdf),
        "fallback_pdf": str(fallback),
        "tailored_pdf_target": str(role_dir / _employer_cv_filename(rc)),
        "tailored_tex_target": str(role_dir / "cv.tex"),
        "jd_path": str(jd_path),
        "hydrated_from_notion": bool(rc.get("hydrated_from_notion")),
        "requires_tailored_cv": bool(rc.get("requires_tailored_cv")),
        "tailoring_required_reasons": rc.get("tailoring_required_reasons", []),
    }, indent=2))
    return 0


# ---------------------------------------------------------------------------
# apply (deterministic walker dispatch)
# ---------------------------------------------------------------------------

def _gate_submission(args) -> None:
    """Refuse to submit applications unless autonomy.level is 'full'.

    --override-autonomy bypasses the gate with a printed warning, for one-off
    supervised runs at a lower autonomy level.
    """
    if getattr(args, "override_autonomy", False):
        print(
            "WARNING: --override-autonomy set; bypassing the autonomy gate "
            f"(autonomy.level is '{autonomy_level()}') and submitting anyway.",
            file=sys.stderr,
        )
        return
    require_autonomy("full", "submit applications automatically")


def cmd_apply(args) -> int:
    _gate_submission(args)
    rid = args.role
    role_dir = resolve_role_dir(rid)
    rc_path = role_dir / "role-context.json"
    rc = json.loads(rc_path.read_text())

    company = (rc.get("company") or "").strip()
    if company and _is_blacklisted_company(company):
        print(json.dumps({"status": "failed", "reason": "company-blacklisted",
                          "company": company, "role_id": rid}))
        return 0

    apply_type = rc.get("apply_type") or "NONE"
    if apply_type == "NONE" and "linkedin.com/jobs/view/" in (rc.get("url") or ""):
        try:
            detail = fetch_jd_and_apply_type(rid)
            refreshed_apply_type = detail.get("applyType") or "NONE"
            if refreshed_apply_type != "NONE":
                rc["apply_type"] = refreshed_apply_type
                apply_type = refreshed_apply_type
            if detail.get("company"):
                rc["company"] = detail["company"]
            refreshed_jd = detail.get("jd") or ""
            if len(refreshed_jd) >= 50:
                (role_dir / "jd.txt").write_text(refreshed_jd)
                rc["requirements"] = _parse_requirements(refreshed_jd)
                try:
                    variant_info = _sv.select_variant(
                        title=rc.get("title") or "",
                        description=refreshed_jd,
                    )
                    rc["variant"] = variant_info.get("variant") or rc.get("variant") or "general"
                except Exception:
                    rc["variant"] = rc.get("variant") or "general"
            rc_path.write_text(json.dumps(rc, indent=2))
        except Exception as e:
            rc["apply_refresh_error"] = str(e)
            rc_path.write_text(json.dumps(rc, indent=2))

    kind, host = classify_apply_type(apply_type)
    if kind == "linkedin_apply" and not host:
        host = "linkedin.com"

    def finish(result: dict, rc_code: int | None = None) -> int:
        result.setdefault("ats_kind", kind)
        result.setdefault("ats_host", host)
        result.setdefault("apply_type", apply_type)
        result.setdefault("role_id", rid)
        result.setdefault("role_url", rc.get("url"))
        status = result.get("status")
        if status in ("failed", "escalate", "expired"):
            reason = str(result.get("reason") or status)
            try:
                from walkers import _pcli as diag_p
                ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
                out_dir = role_dir / "diagnostics" / f"{ts}-{_slugify(reason, max_len=60)}"
                diagnostics = diag_p.capture_diagnostics(
                    SESSION_NAME,
                    out_dir,
                    reason=reason,
                    metadata={
                        "role_id": rid,
                        "title": rc.get("title"),
                        "company": rc.get("company"),
                        "ats_kind": kind,
                        "ats_host": host,
                        "apply_type": apply_type,
                        "result": result,
                    },
                )
                result["diagnostics"] = diagnostics
            except Exception as e:
                result["diagnostics_error"] = str(e)

            # Write a partial-submission-log.json so the user can resume
            # without re-entering information.  This captures:
            #   - answers_filled: fields successfully filled before the halt
            #   - unfilled_fields: required fields that were not filled
            #   - draft_preserved: True when the ATS keeps the draft alive
            #     (LinkedIn: Discard was intentionally NOT clicked)
            try:
                payload = result.get("payload") or {}
                # Normalise the two naming conventions used across walkers:
                # LinkedIn uses "answers_filled_so_far"; external ATS walkers
                # use "answers_filled".
                answers_filled = (
                    payload.get("answers_filled_so_far")
                    or payload.get("answers_filled")
                    or result.get("screening")
                    or {}
                )
                # Unfilled fields: normalise across walker naming conventions
                unfilled_fields = (
                    payload.get("unfilled_required")
                    or payload.get("unfilled")
                    or payload.get("stuck_fields")
                    or []
                )
                partial_log = {
                    "job_id": rid,
                    "company": rc.get("company"),
                    "title": rc.get("title"),
                    "ats_kind": kind,
                    "apply_url": apply_type[4:] if isinstance(apply_type, str) and apply_type.startswith("EXT:") else apply_type,
                    "halted_at": dt.datetime.now().isoformat(),
                    "halt_reason": reason,
                    "status": status,
                    "draft_preserved": payload.get("draft_preserved", False),
                    "resume_note": (
                        payload.get("resume_note")
                        or payload.get("note")
                        or ("LinkedIn draft preserved (Discard NOT clicked). "
                            "Navigate to the job URL to resume." if kind == "linkedin_apply" else
                            "Re-navigate to the apply URL; pre-filled fields "
                            "will need to be re-entered unless the ATS saved a draft.")
                    ),
                    "answers_filled": answers_filled,
                    "unfilled_fields": unfilled_fields,
                    "cv_used": str(_resolve_cv_path(rid)),
                    "variant": rc.get("variant"),
                }
                partial_log_path = role_dir / "partial-submission-log.json"
                partial_log_path.write_text(json.dumps(partial_log, indent=2))
                result["partial_log"] = str(partial_log_path)
            except Exception as e:
                result["partial_log_error"] = str(e)

        if status == "expired":
            try:
                page_id = resolve_page_id(rid)
                notion_run("update-status", page_id, STATUS_EXPIRED)
                notion_run(
                    "append-notes",
                    page_id,
                    f"Marked Expired {dt.date.today().isoformat()}: {result.get('reason') or 'application closed'}.",
                )
                result["notion_status"] = STATUS_EXPIRED
            except Exception as e:
                result["notion_update_error"] = str(e)
        print(json.dumps(result))
        if rc_code is not None:
            return rc_code
        return 0 if status in ("applied", "escalate", "expired") else 1

    # rate-limit guard for LinkedIn (autonomy.max_daily_linkedin_applications)
    if (kind == "linkedin_apply"
            and count_today_linkedin_submissions() >= MAX_DAILY_LINKEDIN_APPLICATIONS):
        return finish({"status": "failed", "reason": "linkedin-rate-limit"}, rc_code=1)

    # ------------------------------------------------------------------
    # Captcha pre-flight: fetch the apply URL and scan for captcha walls
    # before dispatching any walker or edge-case agent.  Only runs for
    # external (EXT:) URLs -- LinkedIn Apply does not go through this path.
    # Fail-open: network errors do NOT block the role.
    # ------------------------------------------------------------------
    if apply_type and apply_type.startswith("EXT:"):
        _apply_url = apply_type[4:]
        try:
            from walkers.captcha_preflight import has_captcha, CAPTCHA_REASON
            _captcha_found, _captcha_marker = has_captcha(_apply_url)
            if _captcha_found:
                return finish(
                    {
                        "status": "failed",
                        "reason": CAPTCHA_REASON,
                        "captcha_marker": _captcha_marker,
                        "note": (
                            f"Captcha wall detected ({_captcha_marker!r}) on "
                            f"{_apply_url[:120]} -- skipped without agent dispatch."
                        ),
                    },
                    rc_code=1,
                )
        except Exception as _preflight_exc:
            # Import or unexpected error: log and continue so the walker
            # still gets a chance.
            pass

    cv_pdf = _ensure_employer_cv_file(rid, rc)
    if not cv_pdf.exists():
        return finish({"status": "failed", "reason": "no-cv-pdf"}, rc_code=1)

    if kind == "linkedin_apply":
        from walkers import linkedin_apply as walker
    elif kind == "greenhouse":
        try:
            from walkers import greenhouse as walker  # noqa: F401
        except ImportError:
            return finish({"status": "escalate", "reason": "greenhouse-walker-not-implemented",
                           "host": host, "url": apply_type[4:]}, rc_code=0)
    elif kind == "workday":
        try:
            from walkers import workday as walker  # noqa: F401
        except ImportError:
            return finish({"status": "escalate", "reason": "workday-walker-not-implemented",
                           "host": host, "url": apply_type[4:]}, rc_code=0)
    elif kind == "lever":
        try:
            from walkers import lever as walker  # noqa: F401
        except ImportError:
            return finish({"status": "escalate", "reason": "lever-walker-not-implemented",
                           "host": host, "url": apply_type[4:]}, rc_code=0)
    elif kind == "ashby":
        try:
            from walkers import ashby as walker  # noqa: F401
        except ImportError:
            return finish({"status": "escalate", "reason": "ashby-walker-not-implemented",
                           "host": host, "url": apply_type[4:]}, rc_code=0)
    elif kind == "smartrecruiters":
        try:
            from walkers import smartrecruiters as walker  # noqa: F401
        except ImportError:
            return finish({"status": "escalate", "reason": "smartrecruiters-walker-not-implemented",
                           "host": host, "url": apply_type[4:]}, rc_code=0)
    elif kind == "teamtailor":
        try:
            from walkers import teamtailor as walker  # noqa: F401
        except ImportError:
            return finish({"status": "escalate", "reason": "teamtailor-walker-not-implemented",
                           "host": host, "url": apply_type[4:]}, rc_code=0)
    elif kind == "bamboohr":
        try:
            from walkers import bamboohr as walker  # noqa: F401
        except ImportError:
            return finish({"status": "escalate", "reason": "bamboohr-walker-not-implemented",
                           "host": host, "url": apply_type[4:]}, rc_code=0)
    elif kind == "jobvite":
        try:
            from walkers import jobvite as walker  # noqa: F401
        except ImportError:
            return finish({"status": "escalate", "reason": "jobvite-walker-not-implemented",
                           "host": host, "url": apply_type[4:]}, rc_code=0)
    elif kind == "wttj":
        try:
            from walkers import wttj as walker  # noqa: F401
        except ImportError:
            return finish({"status": "escalate", "reason": "wttj-walker-not-implemented",
                           "host": host, "url": apply_type[4:]}, rc_code=0)
    elif kind == "none":
        # Distinguish "job is closed" from genuine no-apply-action. If LinkedIn
        # shows "No longer accepting applications", mark Expired so the role
        # doesn't sit on the failed pile.
        try:
            pcli("goto", rc.get("url") or "", timeout=20)
            time.sleep(1.5)
            page_text = pcli_eval(
                "(() => (document.body.innerText || '').slice(0, 4000))()"
            )
        except Exception:
            page_text = ""
        if isinstance(page_text, str) and re.search(
            r"no longer accepting applications"
            r"|applications are no longer being accepted"
            r"|this job is no longer",
            page_text, re.IGNORECASE,
        ):
            return finish({"status": "expired",
                           "reason": "linkedin-no-longer-accepting-applications",
                           "role_url": rc.get("url")}, rc_code=0)
        return finish({"status": "failed", "reason": "no-apply-action-found"}, rc_code=1)
    elif kind == "not_automatable":
        if apply_type.startswith("EXT:"):
            try:
                pcli("goto", apply_type[4:], timeout=30)
                time.sleep(2)
            except Exception:
                pass
        return finish({"status": "failed",
                       "reason": f"not-automatable-host:{host}",
                       "url": apply_type[4:],
                       "note": "Aggregator/mailto redirect — no submittable web form. Apply manually if wanted."},
                      rc_code=1)
    else:
        unknown_url = apply_type[4:] if apply_type.startswith("EXT:") else apply_type
        page_snapshot_tail = ""
        if apply_type.startswith("EXT:"):
            try:
                pcli("goto", unknown_url, timeout=30)
                time.sleep(2)
                # Capture a brief snapshot tail so the edge-case agent can
                # identify the ATS without needing to re-navigate.
                snap_raw = pcli_eval(
                    "(() => document.body.innerText.slice(0, 1500))()"
                )
                if isinstance(snap_raw, str):
                    page_snapshot_tail = snap_raw
            except Exception:
                pass
        return finish({"status": "escalate",
                       "reason": f"unknown-ats:{host or 'unknown'}",
                       "host": host,
                       "url": unknown_url,
                       "page_text_preview": page_snapshot_tail,
                       "note": (
                           f"ATS host '{host or 'unknown'}' is not handled by any "
                           f"walker. The browser has been navigated to the apply URL. "
                           f"Edge-case agent should inspect the page and either drive "
                           f"the form manually or mark as HUMAN_REQUIRED."
                       )},
                      rc_code=0)

    # Walker contract: walk(role_context_dict, cv_pdf_path: Path, session_name: str)
    #   -> {status: "applied"|"escalate"|"failed", reason?: str, screening?: dict, ...}
    result = walker.walk(rc, cv_pdf, SESSION_NAME)
    return finish(result)


def cmd_mark_applied(args) -> int:
    rid = args.role
    role_dir = resolve_role_dir(rid)
    rc = json.loads((role_dir / "role-context.json").read_text())
    screening_raw = json.loads(args.screening) if args.screening else {}
    # Annotate any AI-drafted answers for post-hoc quality analysis.
    # The AI screening log records which answers were auto-filled; cross-reference
    # here so the submission log carries ai_drafted=True per answer.
    ai_log_path = role_dir / "ai-screening-log.json"
    ai_filled_labels: set[str] = set()
    if ai_log_path.exists():
        try:
            ai_entries = json.loads(ai_log_path.read_text())
            if isinstance(ai_entries, list):
                ai_filled_labels = {
                    e["label"] for e in ai_entries if e.get("auto_filled") and e.get("label")
                }
        except (json.JSONDecodeError, OSError):
            pass
    if isinstance(screening_raw, dict) and ai_filled_labels:
        screening_annotated = {
            label: {"value": val, "ai_drafted": label in ai_filled_labels}
            for label, val in screening_raw.items()
        }
    else:
        screening_annotated = screening_raw
    log = {
        "job_id": rid,
        "company": rc.get("company"),
        "title": rc.get("title"),
        "submitted_via": args.via or "LinkedIn Apply",
        "submitted_at": dt.datetime.now().isoformat(),
        "cv_used": str(_resolve_cv_path(rid)),
        "variant": rc.get("variant"),
        "screening_answers": screening_annotated,
        "confirmation": args.confirmation or "",
    }
    (role_dir / "submission-log.json").write_text(json.dumps(log, indent=2))
    page_id = resolve_page_id(rid)
    notes = (
        f"Applied {dt.date.today().isoformat()} via {log['submitted_via']}. "
        f"CV: {Path(log['cv_used']).name}."
    )
    # Post-submit state in the v2 schema is AwaitingResponse, not "Applied"
    # (which no longer exists in Notion's Status field).
    notion_run("update-status", page_id, STATUS_AWAITING_RESPONSE)
    notion_run("set-artefacts", page_id, f"--applied-date={dt.date.today().isoformat()}")
    notion_run("append-notes", page_id, notes)
    print(f"mark-applied {rid}: OK (status=AwaitingResponse)")
    return 0


def _resolve_cv_path(rid: str) -> Path:
    role_dir = resolve_role_dir(rid)
    rc_path = role_dir / "role-context.json"
    rc = json.loads(rc_path.read_text()) if rc_path.exists() else {}
    for employer in _employer_cv_candidates(role_dir, rc):
        if employer.exists():
            return employer
    p = role_dir / "cv.pdf"
    if p.exists():
        return p
    return role_dir / "cv-template-fallback.pdf"


# ---------------------------------------------------------------------------
# batch-apply
# ---------------------------------------------------------------------------

def cmd_batch_apply(args) -> int:
    """Walker pass on multiple roles; auto-marks applied/failed/expired inline.

    Writes a JSON results file so the orchestrator can dispatch edge-case
    agents for the escalated bucket without reading walker output into context.

    Output (stdout): one compact summary line, nothing else.
    """
    _gate_submission(args)
    # Resolve role IDs
    if args.roles_file:
        ids = json.loads(Path(args.roles_file).read_text())
    else:
        limit = args.limit or 50
        rows = json.loads(subprocess.check_output(
            [sys.executable, __file__, "list-queue",
             "--status", args.status, "--limit", str(limit)],
            text=True,
        ))
        ids = [r["id"] for r in rows]

    if not ids:
        print(f"batch-apply: 0 roles in {args.status}")
        return 0

    # Output file
    out_path = Path(args.output_file) if args.output_file else (
        Path("/tmp") / f"batch-apply-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    )

    results: dict[str, list] = {"applied": [], "escalated": [], "failed": [], "expired": []}

    for rid in ids:
        # Run single walker (cmd_apply resolves the CV via _ensure_employer_cv_file)
        apply_cmd = [sys.executable, __file__, "apply", "--role", rid]
        if getattr(args, "override_autonomy", False):
            # Forward the bypass so the child `apply` passes its own gate.
            apply_cmd.append("--override-autonomy")
        r = subprocess.run(
            apply_cmd,
            capture_output=True, text=True,
        )
        try:
            result = json.loads(r.stdout.strip().splitlines()[-1])
        except Exception:
            result = {"status": "failed", "reason": "parse-error", "role_id": rid}

        status = result.get("status", "failed")

        if status == "applied":
            subprocess.run(
                [sys.executable, __file__, "mark-applied",
                 "--role", rid,
                 "--via", result.get("submitted_via") or "unknown",
                 "--confirmation", result.get("confirmation") or ""],
                capture_output=True,
            )
            results["applied"].append(rid)

        elif status == "escalate":
            esc_reason = result.get("reason") or ""
            intel = _load_intelligence()
            playbook = intel.get("escalation_playbooks", {}).get(esc_reason, {})
            if playbook.get("action") == "skip":
                subprocess.run(
                    [sys.executable, __file__, "mark-failed",
                     "--role", rid,
                     "--reason", f"auto-skipped: {playbook.get('reason', esc_reason)}"],
                    capture_output=True,
                )
                results["failed"].append(rid)
                print(f"  {rid} auto-skipped ({esc_reason})", file=sys.stderr)
                continue

            role_dir = resolve_role_dir(rid)
            rc_path = role_dir / "role-context.json"
            rc = json.loads(rc_path.read_text()) if rc_path.exists() else {}
            cv = str(_resolve_cv_path(rid))
            # For LinkedIn Apply escalations, pre-open and pre-authenticate the
            # agent session so it inherits LinkedIn cookies without needing to
            # call state-load itself. The session is left open; the agent must
            # use `goto` rather than `open` to avoid resetting the context.
            payload = dict(result.get("payload") or {})
            ats_kind = result.get("ats_kind") or ""
            if ats_kind == "linkedin_apply" and LINKEDIN_STATE.exists():
                agent_session = f"apply-{rid}"
                subprocess.run(
                    ["playwright-cli", f"-s={agent_session}", "close"],
                    capture_output=True, text=True,
                )
                r_open = subprocess.run(
                    ["playwright-cli", f"-s={agent_session}", "open"],
                    capture_output=True, text=True, timeout=30,
                )
                r_load = subprocess.run(
                    ["playwright-cli", f"-s={agent_session}", "state-load",
                     str(LINKEDIN_STATE)],
                    capture_output=True, text=True, timeout=30,
                )
                if r_open.returncode == 0 and r_load.returncode == 0:
                    payload["session_preloaded"] = True
            results["escalated"].append({
                "id": rid,
                "reason": result.get("reason") or "",
                "payload": payload,
                "cv": cv,
                "title": rc.get("title") or "",
                "company": rc.get("company") or "",
            })

        elif status == "expired":
            # cmd_apply already wrote Expired to Notion; just bucket it
            results["expired"].append(rid)

        else:  # failed
            subprocess.run(
                [sys.executable, __file__, "mark-failed",
                 "--role", rid,
                 "--reason", result.get("reason") or "walker-error"],
                capture_output=True,
            )
            results["failed"].append(rid)

    out_path.write_text(json.dumps(results, indent=2))

    a = len(results["applied"])
    e = len(results["escalated"])
    f = len(results["failed"])
    x = len(results["expired"])
    print(
        f"batch-apply: {len(ids)} roles | "
        f"applied={a} escalated={e} failed={f} expired={x} | "
        f"results={out_path}"
    )
    return 0


# summary
# ---------------------------------------------------------------------------

def cmd_summary(args) -> int:
    today = dt.date.today().isoformat()
    # Show v2 active statuses; collapse downstream pipeline into one count
    # (response/interview stages aren't owned by auto-apply).
    active = (STATUS_NEEDS_TAILORING, STATUS_READY_TO_APPLY,
              STATUS_AWAITING_RESPONSE, STATUS_ESCALATED, STATUS_FAILED)
    counts: dict[str, int] = {s: 0 for s in active}
    downstream = 0
    for status in active:
        try:
            data = json.loads(notion_run("list-by-status", status))
            counts[status] = len(data)
        except Exception:
            pass
    for status in ("ResponseReceived", "PhoneScreen", "Test",
                   "CultureInterview", "TechnicalInterview", "FinalRound",
                   "Offer", "Accepted"):
        try:
            data = json.loads(notion_run("list-by-status", status))
            downstream += len(data)
        except Exception:
            pass
    submitted_today = count_today_linkedin_submissions()
    print("# auto-apply summary")
    print(f"date: {today}")
    print(f"LinkedIn submissions today: {submitted_today} / {MAX_DAILY_LINKEDIN_APPLICATIONS}")
    print()
    for k, v in counts.items():
        print(f"- {k}: {v}")
    print(f"- Downstream (Response/Interview/Offer/Accepted): {downstream}")
    return 0


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(prog="auto_apply", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("session-open").set_defaults(func=cmd_session_open)
    sub.add_parser("session-close").set_defaults(func=cmd_session_close)

    sp = sub.add_parser("search")
    sp.add_argument("--date", default="24h", choices=list(DATE_MAP))
    sp.add_argument("--location", default=_DEFAULT_LOCATIONS,
                    help="Comma-separated location keys from search.locations "
                         "in data/search_config.json. Defaults to "
                         "search.default_locations.")
    sp.add_argument("--term", default=_DEFAULT_QUERIES,
                    help="Comma-separated semantic-query keys from "
                         "search.queries in data/search_config.json, or "
                         "literal natural-language phrases. Defaults to "
                         "search.default_queries.")
    sp.add_argument("--per-query", type=int, default=5,
                    help="Max APPLY rows accepted per search URL. Each "
                         "(query x location) pair is one URL, so this caps "
                         "the search-stage queue at URL-count x per-query "
                         "roles. Ensures fair coverage across queries (no "
                         "single query exhausts the budget). Default 5.")
    sp.add_argument("--max-roles", type=int, default=0,
                    help="OPTIONAL global ceiling on APPLY rows across all "
                         "URLs. Defaults to a generous bound derived from "
                         "--per-query x URL-count. Use this only as a hard "
                         "safety stop; per-query is the primary knob.")
    sp.set_defaults(func=cmd_search)

    sp = sub.add_parser("list-queue")
    sp.add_argument("--status", required=True)
    sp.add_argument("--limit", type=int, default=0,
                    help="Cap returned rows. 0 = no cap. Used by the "
                         "orchestrator to enforce --max-tailor / --max-apply "
                         "stage caps.")
    sp.set_defaults(func=cmd_list_queue)

    sp = sub.add_parser("prepare")
    sp.add_argument("--role", required=True)
    sp.add_argument("--jd-file",
                    help="Path to a job description for older Notion rows "
                         "that do not have Job Description stored.")
    sp.add_argument("--jd-text",
                    help="Inline job description for older Notion rows that "
                         "do not have Job Description stored.")
    sp.set_defaults(func=cmd_prepare)

    sp = sub.add_parser("mark-ready")
    sp.add_argument("--role", required=True)
    sp.set_defaults(func=cmd_mark_ready)

    sp = sub.add_parser("apply")
    sp.add_argument("--role", required=True)
    sp.add_argument("--override-autonomy", action="store_true",
                    help="Bypass the autonomy.level gate and submit even when "
                         "autonomy.level is below 'full'. Prints a warning.")
    sp.set_defaults(func=cmd_apply)

    sp = sub.add_parser("mark-applied")
    sp.add_argument("--role", required=True)
    sp.add_argument("--via", default="LinkedIn Apply")
    sp.add_argument("--screening", help="JSON object of screening answers")
    sp.add_argument("--confirmation", default="")
    sp.set_defaults(func=cmd_mark_applied)

    sp = sub.add_parser("mark-escalated")
    sp.add_argument("--role", required=True)
    sp.add_argument("--reason", required=True)
    sp.set_defaults(func=lambda a: cmd_mark_status(a, STATUS_ESCALATED, a.reason))

    sp = sub.add_parser("mark-failed")
    sp.add_argument("--role", required=True)
    sp.add_argument("--reason", required=True)
    sp.set_defaults(func=lambda a: cmd_mark_status(a, STATUS_FAILED, a.reason))

    sp = sub.add_parser("mark-expired")
    sp.add_argument("--role", required=True)
    sp.add_argument("--reason", default="No longer accepting applications")
    sp.set_defaults(func=lambda a: cmd_mark_status(a, STATUS_EXPIRED, a.reason))

    sp = sub.add_parser("mark-skip")
    sp.add_argument("--role", required=True)
    sp.add_argument("--reason", default="Skipped by auto-apply policy")
    sp.set_defaults(func=lambda a: cmd_mark_status(a, STATUS_SKIP, a.reason))

    sp = sub.add_parser("batch-apply",
                        help="Run the ATS walker on multiple roles serially, "
                             "auto-mark applied/failed/expired, and write an "
                             "escalations JSON file for the orchestrator to "
                             "dispatch edge-case agents against.")
    sp.add_argument("--roles-file",
                    help="Path to a JSON array of LinkedIn role IDs. "
                         "If omitted, pulls from --status queue.")
    sp.add_argument("--status", default="ReadyToApply",
                    help="Notion status to pull when --roles-file is not given.")
    sp.add_argument("--limit", type=int, default=15,
                    help="Max roles to process (ignored when --roles-file is given).")
    sp.add_argument("--output-file", default="",
                    help="Path for the results JSON. Defaults to "
                         "/tmp/batch-apply-<timestamp>.json.")
    sp.add_argument("--override-autonomy", action="store_true",
                    help="Bypass the autonomy.level gate and submit even when "
                         "autonomy.level is below 'full'. Prints a warning.")
    sp.set_defaults(func=cmd_batch_apply)

    sub.add_parser("summary").set_defaults(func=cmd_summary)

    args = p.parse_args()
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
