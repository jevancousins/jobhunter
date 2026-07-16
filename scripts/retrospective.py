#!/usr/bin/env python3
"""retrospective.py: generate data/apply-intelligence.json from Notion outcomes + local data.

Joins Notion job statuses with local submission-log.json, role-context.json,
and diagnostics data to produce an intelligence file that the pipeline reads
at decision points (variant selection, ATS routing, escalation triage).

Usage:
    python scripts/retrospective.py              # full retrospective
    python scripts/retrospective.py --quick      # quick mode (skip Notion, local data only)
    python scripts/retrospective.py --dry-run    # print to stdout, don't write file
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
APPLICATIONS_DIR = ROOT / "applications"
INTELLIGENCE_PATH = ROOT / "data" / "apply-intelligence.json"

sys.path.insert(0, str(ROOT / "scripts"))
from notion_cli import NotionClient, _page_to_summary  # noqa: E402

try:
    from select_variant import get_default_variant  # noqa: E402
except Exception:  # pragma: no cover - variant selector unavailable
    def get_default_variant() -> str:
        return "general"

POSITIVE_STATUSES = {
    "ResponseReceived", "PhoneScreen", "Test",
    "CultureInterview", "TechnicalInterview", "FinalRound",
    "Offer", "Accepted",
}
NEGATIVE_STATUSES = {"Rejected", "NoResponse", "Expired"}
APPLIED_STATUSES = {"AwaitingResponse"} | POSITIVE_STATUSES | NEGATIVE_STATUSES


def load_all_notion_jobs(client: NotionClient) -> list[dict]:
    """Fetch every job from Notion that has been applied to or resolved."""
    all_jobs: list[dict] = []
    for status in APPLIED_STATUSES:
        cursor = None
        while True:
            kwargs: dict[str, Any] = {
                "filter": {"property": "Status", "status": {"equals": status}},
                "page_size": 100,
            }
            if cursor:
                kwargs["start_cursor"] = cursor
            response = client.query_database(client.jobs_db_id, **kwargs)
            all_jobs.extend([_page_to_summary(p) for p in response["results"]])
            if not response.get("has_more"):
                break
            cursor = response.get("next_cursor")
    return all_jobs


def _iter_role_dirs():
    """Yield every per-role folder regardless of flat or nested layout.

    Flat layout: `applications/<role-id>/role-context.json`
    Nested layout: `applications/<Company>/<role-id>/role-context.json`
    """
    if not APPLICATIONS_DIR.exists():
        return
    for sub in APPLICATIONS_DIR.iterdir():
        if not sub.is_dir() or sub.name.startswith("."):
            continue
        if (sub / "role-context.json").exists() or (sub / "submission-log.json").exists():
            yield sub
            continue
        # Treat as company folder containing role-id subdirs
        for child in sub.iterdir():
            if child.is_dir():
                yield child


def load_local_submissions() -> dict[str, dict]:
    """Load all submission-log.json files keyed by role ID."""
    submissions: dict[str, dict] = {}
    for role_dir in _iter_role_dirs():
        log_path = role_dir / "submission-log.json"
        if log_path.exists():
            with log_path.open() as f:
                submissions[role_dir.name] = json.load(f)
    return submissions


def load_local_role_contexts() -> dict[str, dict]:
    """Load all role-context.json files keyed by role ID."""
    contexts: dict[str, dict] = {}
    for role_dir in _iter_role_dirs():
        rc_path = role_dir / "role-context.json"
        if rc_path.exists():
            with rc_path.open() as f:
                contexts[role_dir.name] = json.load(f)
    return contexts


def load_tailoring_decisions() -> dict[str, dict]:
    """Load all tailoring-decisions.json files keyed by role ID."""
    decisions: dict[str, dict] = {}
    for role_dir in _iter_role_dirs():
        td_path = role_dir / "tailoring-decisions.json"
        if td_path.exists():
            with td_path.open() as f:
                decisions[role_dir.name] = json.load(f)
    return decisions


def count_escalation_diagnostics() -> Counter:
    """Count escalation failure reasons across all diagnostic folders.

    Supports both the legacy flat layout (`applications/<role-id>/diagnostics/`)
    and the new nested layout (`applications/<Company>/<role-id>/diagnostics/`).
    """
    reasons: Counter = Counter()
    if not APPLICATIONS_DIR.exists():
        return reasons
    # Glob both depths so the count survives the company-folder restructure.
    diag_dirs = list(APPLICATIONS_DIR.glob("*/diagnostics")) + list(
        APPLICATIONS_DIR.glob("*/*/diagnostics")
    )
    for diag_dir in diag_dirs:
        if not diag_dir.is_dir():
            continue
        for subdir in diag_dir.iterdir():
            if not subdir.is_dir():
                continue
            for f in subdir.iterdir():
                if f.name.endswith(".metadata.json"):
                    reason = f.name.replace(".metadata.json", "")
                    reasons[reason] += 1
    return reasons


def match_notion_to_local(
    notion_jobs: list[dict],
    role_contexts: dict[str, dict],
    submissions: dict[str, dict],
) -> list[dict]:
    """Join Notion jobs with local data by URL or company+title matching."""
    notion_url_index: dict[str, dict] = {}
    for job in notion_jobs:
        url = job.get("url", "")
        if url:
            job_id = url.rstrip("/").split("/")[-1]
            notion_url_index[job_id] = job

    joined: list[dict] = []
    for role_id, rc in role_contexts.items():
        entry = {
            "role_id": role_id,
            "title": rc.get("title", ""),
            "company": rc.get("company", ""),
            "location": rc.get("location", ""),
            "variant": rc.get("variant", "unknown"),
            "apply_type": rc.get("apply_type", "unknown"),
            "notion_status": None,
            "submitted": role_id in submissions,
            "submitted_via": None,
        }

        if role_id in submissions:
            sub = submissions[role_id]
            entry["submitted_via"] = sub.get("submitted_via", "unknown")
            entry["variant"] = sub.get("variant", entry["variant"])

        notion_match = notion_url_index.get(role_id)
        if notion_match:
            entry["notion_status"] = notion_match.get("status")
            entry["notion_location"] = notion_match.get("location")

        joined.append(entry)

    return joined


def compute_variant_outcomes(joined: list[dict]) -> dict:
    """Compute response rates per variant."""
    variant_stats: dict[str, dict] = defaultdict(
        lambda: {"submitted": 0, "positive": 0, "rejected": 0, "awaiting": 0, "titles": []}
    )
    for entry in joined:
        if not entry["submitted"]:
            continue
        v = entry["variant"]
        variant_stats[v]["submitted"] += 1
        status = entry.get("notion_status")
        if status in POSITIVE_STATUSES:
            variant_stats[v]["positive"] += 1
            variant_stats[v]["titles"].append(entry["title"])
        elif status in NEGATIVE_STATUSES:
            variant_stats[v]["rejected"] += 1
        elif status == "AwaitingResponse":
            variant_stats[v]["awaiting"] += 1

    result = {}
    for v, stats in sorted(variant_stats.items(), key=lambda x: -x[1]["submitted"]):
        resolved = stats["positive"] + stats["rejected"]
        rate = stats["positive"] / resolved if resolved > 0 else None
        result[v] = {
            "submitted": stats["submitted"],
            "positive": stats["positive"],
            "rejected": stats["rejected"],
            "awaiting": stats["awaiting"],
            "response_rate": round(rate, 3) if rate is not None else None,
            "positive_titles": stats["titles"][:5],
        }
    return result


def compute_variant_boosts(variant_outcomes: dict) -> list[dict]:
    """Identify variants that outperform the default for specific title patterns."""
    boosts = []
    default_variant = get_default_variant()
    default_stats = variant_outcomes.get(default_variant, {})
    default_rate = default_stats.get("response_rate")

    for variant, stats in variant_outcomes.items():
        if variant == default_variant:
            continue
        rate = stats.get("response_rate")
        if rate is None or stats["submitted"] < 2:
            continue
        if rate > (default_rate or 0):
            default_pos = default_stats.get("positive", 0)
            default_sub = default_stats.get("submitted", 0)
            default_str = (
                f"{default_pos}/{default_sub} ({default_rate:.1%})"
                if default_rate is not None
                else f"{default_pos}/{default_sub} (0.0%)"
            )
            boosts.append({
                "preferred_variant": variant,
                "response_rate": rate,
                "sample_size": stats["submitted"],
                "positive_count": stats["positive"],
                "evidence": (
                    f"{stats['positive']}/{stats['submitted']} positive "
                    f"({rate:.1%}) vs {default_variant} {default_str}"
                ),
            })

    boosts.sort(key=lambda x: -(x.get("response_rate") or 0))
    return boosts


def compute_ats_success_rates(joined: list[dict]) -> dict:
    """Compute submission success rates by ATS channel."""
    channel_stats: dict[str, dict] = defaultdict(
        lambda: {"attempted": 0, "submitted": 0, "positive": 0}
    )
    for entry in joined:
        via = entry.get("submitted_via") or "unknown"
        via_normalised = _normalise_channel(via)
        if entry["submitted"]:
            channel_stats[via_normalised]["submitted"] += 1
            if entry.get("notion_status") in POSITIVE_STATUSES:
                channel_stats[via_normalised]["positive"] += 1

    return {
        ch: {
            "submitted": s["submitted"],
            "positive": s["positive"],
            "response_rate": round(s["positive"] / s["submitted"], 3) if s["submitted"] > 0 else None,
        }
        for ch, s in sorted(channel_stats.items(), key=lambda x: -x[1]["submitted"])
    }


def _normalise_channel(via: str) -> str:
    """Group similar channels into canonical names."""
    v = via.lower().strip()
    if "linkedin" in v:
        return "LinkedIn Apply"
    if "greenhouse" in v:
        return "Greenhouse"
    if "ashby" in v:
        return "Ashby"
    if "lever" in v:
        return "Lever"
    if "workday" in v:
        return "Workday"
    if "teamtailor" in v:
        return "TeamTailor"
    if "smartrecruiters" in v:
        return "SmartRecruiters"
    if "bamboohr" in v:
        return "BambooHR"
    if "jobvite" in v:
        return "Jobvite"
    if "micro1" in v:
        return "Micro1"
    return via


def compute_skip_hosts(diagnostics: Counter, threshold: int = 8) -> list[str]:
    """Identify ATS hosts that should be skipped (tried many times, never succeeded)."""
    skip = []
    redirects_and_ads = {
        "ad.doubleclick.net", "jsv3.recruitics.com",
    }
    for reason, count in diagnostics.most_common():
        if not reason.startswith("unknown-ats-"):
            continue
        host = reason.replace("unknown-ats-", "")
        if count >= threshold or host in redirects_and_ads:
            skip.append(host)
    return sorted(skip)


# Hand-curated skip reasons that should always be honoured, even if they have
# zero hits in the local diagnostics. Added when a reason is observed in the
# wild but has not yet been emitted by a Python walker (e.g. agent-reported
# reasons like the various Ashby spam-filter aliases).
SEED_SKIP_REASONS: dict[str, str] = {
    "ashby-spam-flag-detected":
        "ATS flagged as spam; repeated attempts may harm reputation",
    "ashby-spam-filter-blocking-submission":
        "Ashby silently blocks programmatic submissions after form validation passes; not bypassable by retries",
    "ashby-spam-detection":
        "Alias of ashby-spam-filter-blocking-submission",
    "ashby-spam-filter-blocked":
        "Alias of ashby-spam-filter-blocking-submission",
    "ashby-spam-filter-blocks-submission":
        "Alias of ashby-spam-filter-blocking-submission",
    "ashby-spam-filter-blocked-submission":
        "Alias of ashby-spam-filter-blocking-submission",
    "ashby-spam-detection-blocks-programmatic-submit":
        "Alias of ashby-spam-filter-blocking-submission",
    "ashby-recaptcha-spam-detection-triggered":
        "Ashby reCAPTCHA flagged the session; submission cannot complete programmatically",
    "ashby-spam-flag-on-submission":
        "Alias of ashby-spam-filter-blocking-submission",
    "video-response-required":
        "Application requires recorded video; not automatable, needs human",
    "ashby-spam-block":
        "Alias of ashby-spam-filter-blocking-submission",
    "ashby-recaptcha-blocks-headless-submission":
        "Ashby reCAPTCHA blocks headless playwright sessions; cannot bypass",
    "recaptcha-blocking-submission":
        "reCAPTCHA blocks programmatic submission; cannot bypass",
    "hcaptcha-blocks-submit":
        "hCaptcha visual challenge blocks programmatic submission",
    "hcaptcha-visual-challenge-blocking-submission":
        "Alias of hcaptcha-blocks-submit",
    "hcaptcha-image-drag-challenge-blocking-lever-submission":
        "hCaptcha drag-puzzle on Lever forms blocks programmatic submission",
    "ashby-spam-bot-detection":
        "Alias of ashby-spam-filter-blocking-submission",
    "targetjobs-requires-login-authentication":
        "TargetJobs aggregator requires user login; cannot automate",
    "successfactors-registration-combobox-select":
        "SuccessFactors requires account registration; cannot automate",
    "equifax-careers-no-apply-form":
        "Equifax careers page has no automatable apply form",
    "recaptcha-protected-form":
        "Form protected by reCAPTCHA; cannot bypass programmatically",
    "recaptcha-image-challenge":
        "reCAPTCHA image challenge; needs human",
    "recaptcha-enterprise-blocks-automation":
        "reCAPTCHA Enterprise detects automation; cannot bypass",
    "recaptcha-and-password-account-creation":
        "reCAPTCHA plus account creation; cannot automate",
    "icims-hcaptcha-gate":
        "iCIMS forms gated by hCaptcha; cannot bypass",
    "icims-gdpr-hcaptcha-gate-blocks-automation":
        "Alias of icims-hcaptcha-gate",
    "cgi-njoyn-radware-captcha-protected":
        "CGI Njoyn protected by Radware captcha",
    "ats-403-blocked":
        "ATS returns 403 to automated requests",
    "successfactors-guest-registration-blocked":
        "SuccessFactors requires guest registration; cannot automate",
    "unknown-ats-successfactors-requires-account-creation":
        "Alias of successfactors-registration-combobox-select",
    "unknown-ats:successfactors-account-creation-required":
        "Alias of successfactors-registration-combobox-select",
    "workday-account-verification-required":
        "Workday account verification gate; cannot automate",
    "ibm-avature-requires-login":
        "IBM Avature portal requires login; cannot automate",
    "google-careers-requires-manual-auth":
        "Google Careers requires manual auth; cannot automate",
    "emagine-portal-requires-auth-setup":
        "Emagine portal requires auth setup; cannot automate",
    "flatchr-french-form-requires-cover-letter":
        "Flatchr forms require cover letter; needs Sonnet drafter",
    "cegid-hr-form-phone-validation-error":
        "Cegid HR form phone validation blocks submission",
    "oracle-cloud-hrm-cv-upload-failed":
        "Oracle Cloud HRM CV upload fails programmatically",
    "ashby-mandatory-video-submission-required":
        "Ashby form requires mandatory video; not automatable",
    "collective-work-custom-ats-file-upload-not-accessible":
        "Collective.work custom ATS file upload not accessible",
    "session-dead-host:careers.ey.com":
        "Session-proven: EY careers blocks all attempts",
    "session-dead-host:careers.equifax.com":
        "Session-proven: Equifax careers blocks all attempts",
    "session-dead-host:careers.google.com":
        "Session-proven: Google careers requires manual auth",
    "ashby-extra-fields-high-captcha-risk":
        "Ashby extra-required-fields pattern has high captcha rate this session",
    "captcha-protected-form":
        "Captcha wall detected by pre-flight scan (reCAPTCHA / hCaptcha / Radware); "
        "skipped before agent dispatch",
}


def compute_escalation_playbooks(diagnostics: Counter, submissions: dict[str, dict]) -> dict:
    """Determine what to do for each escalation reason based on historical success."""
    submitted_reasons: Counter = Counter()
    for role_id, sub in submissions.items():
        via = sub.get("submitted_via", "")
        if via and via != "LinkedIn Apply":
            submitted_reasons[via] += 1

    playbooks = {}
    for reason, count in diagnostics.most_common():
        if reason.startswith("unknown-ats-"):
            continue
        if count < 3:
            continue

        if "workday-account-creation" in reason:
            playbooks[reason] = {
                "action": "skip",
                "count": count,
                "reason": f"0/{count} ever succeeded (requires manual account creation)",
            }
        elif "needs_human" in reason:
            playbooks[reason] = {
                "action": "skip",
                "count": count,
                "reason": "requires human intervention by design",
            }
        elif "not-automatable" in reason:
            playbooks[reason] = {
                "action": "skip",
                "count": count,
                "reason": "recruiter redirect or no submittable form",
            }
        elif "expired" in reason or "no-longer-accepting" in reason:
            playbooks[reason] = {
                "action": "skip",
                "count": count,
                "reason": "role expired before submission attempt",
            }
        elif "spam" in reason:
            playbooks[reason] = {
                "action": "skip",
                "count": count,
                "reason": "ATS flagged as spam; repeated attempts may harm reputation",
            }
        else:
            playbooks[reason] = {
                "action": "escalate",
                "count": count,
                "reason": f"seen {count} times; edge-case agent may succeed",
            }

    # Always include hand-curated skip seeds, even if absent from diagnostics
    # or below the count threshold. Diagnostic-derived entries win on count.
    for reason, why in SEED_SKIP_REASONS.items():
        if reason in playbooks:
            continue
        playbooks[reason] = {
            "action": "skip",
            "count": diagnostics.get(reason, 0),
            "reason": why,
        }

    return playbooks


def compute_tailoring_insights(
    tailoring_decisions: dict[str, dict],
    joined: list[dict],
) -> dict:
    """Cross-reference tailoring decisions with outcomes."""
    status_by_role = {e["role_id"]: e.get("notion_status") for e in joined}
    insights: dict[str, Any] = {
        "total_tailored": len(tailoring_decisions),
        "profile_rewrite_outcomes": {"with": {"positive": 0, "total": 0}, "without": {"positive": 0, "total": 0}},
        "bullet_swap_outcomes": {"with": {"positive": 0, "total": 0}, "without": {"positive": 0, "total": 0}},
        "skills_added_frequency": Counter(),
    }

    for role_id, td in tailoring_decisions.items():
        status = status_by_role.get(role_id)
        if status not in (POSITIVE_STATUSES | NEGATIVE_STATUSES):
            continue
        is_positive = status in POSITIVE_STATUSES

        if td.get("profile_rewritten"):
            insights["profile_rewrite_outcomes"]["with"]["total"] += 1
            if is_positive:
                insights["profile_rewrite_outcomes"]["with"]["positive"] += 1
        else:
            insights["profile_rewrite_outcomes"]["without"]["total"] += 1
            if is_positive:
                insights["profile_rewrite_outcomes"]["without"]["positive"] += 1

        if td.get("bullets_swapped", 0) > 0:
            insights["bullet_swap_outcomes"]["with"]["total"] += 1
            if is_positive:
                insights["bullet_swap_outcomes"]["with"]["positive"] += 1
        else:
            insights["bullet_swap_outcomes"]["without"]["total"] += 1
            if is_positive:
                insights["bullet_swap_outcomes"]["without"]["positive"] += 1

        for skill in td.get("skills_added", []):
            insights["skills_added_frequency"][skill] += 1

    insights["skills_added_frequency"] = dict(
        insights["skills_added_frequency"].most_common(20)
    )
    return insights


def build_intelligence(
    notion_jobs: list[dict] | None,
    quick: bool = False,
) -> dict:
    """Build the complete intelligence file."""
    submissions = load_local_submissions()
    role_contexts = load_local_role_contexts()
    tailoring_decisions = load_tailoring_decisions()
    diagnostics = count_escalation_diagnostics()

    if notion_jobs is not None:
        joined = match_notion_to_local(notion_jobs, role_contexts, submissions)
    else:
        joined = []
        for role_id, rc in role_contexts.items():
            joined.append({
                "role_id": role_id,
                "title": rc.get("title", ""),
                "company": rc.get("company", ""),
                "variant": submissions.get(role_id, {}).get("variant", rc.get("variant", "unknown")),
                "submitted": role_id in submissions,
                "submitted_via": submissions.get(role_id, {}).get("submitted_via"),
                "notion_status": None,
            })

    variant_outcomes = compute_variant_outcomes(joined)
    variant_boosts = compute_variant_boosts(variant_outcomes)
    ats_rates = compute_ats_success_rates(joined)
    skip_hosts = compute_skip_hosts(diagnostics)
    playbooks = compute_escalation_playbooks(diagnostics, submissions)
    tailoring_insights = compute_tailoring_insights(tailoring_decisions, joined)

    total_submitted = sum(1 for e in joined if e["submitted"])
    total_positive = sum(
        1 for e in joined
        if e.get("notion_status") in POSITIVE_STATUSES
    )
    total_rejected = sum(
        1 for e in joined
        if e.get("notion_status") in NEGATIVE_STATUSES
    )

    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "mode": "quick" if quick else "full",
        "summary": {
            "total_roles_tracked": len(role_contexts),
            "total_submitted": total_submitted,
            "total_positive_outcomes": total_positive,
            "total_rejected": total_rejected,
            "overall_response_rate": (
                round(total_positive / (total_positive + total_rejected), 3)
                if (total_positive + total_rejected) > 0 else None
            ),
            "total_escalation_diagnostics": sum(diagnostics.values()),
        },
        "variant_outcomes": variant_outcomes,
        "variant_boosts": variant_boosts,
        "ats_success_rates": ats_rates,
        "skip_hosts": skip_hosts,
        "escalation_playbooks": playbooks,
        "tailoring_insights": tailoring_insights,
    }


def print_delta_summary(intelligence: dict) -> None:
    """Print a concise summary to stderr for the post-run step."""
    s = intelligence["summary"]
    print(f"Retrospective: {s['total_submitted']} submitted, "
          f"{s['total_positive_outcomes']} positive, "
          f"{s['total_rejected']} rejected", file=sys.stderr)
    rate = s.get("overall_response_rate")
    if rate is not None:
        print(f"Overall response rate: {rate:.1%}", file=sys.stderr)

    boosts = intelligence.get("variant_boosts", [])
    if boosts:
        top = boosts[0]
        print(f"Top variant: {top['preferred_variant']} "
              f"({top['response_rate']:.1%} rate, n={top['sample_size']})", file=sys.stderr)

    skips = intelligence.get("skip_hosts", [])
    if skips:
        print(f"Skip hosts: {len(skips)} ATS hosts blacklisted", file=sys.stderr)

    playbooks = intelligence.get("escalation_playbooks", {})
    skip_count = sum(1 for p in playbooks.values() if p.get("action") == "skip")
    if skip_count:
        print(f"Escalation playbooks: {skip_count} reasons auto-skipped", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate apply-intelligence.json")
    parser.add_argument("--quick", action="store_true",
                        help="Skip Notion queries; use local data only")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print to stdout instead of writing file")
    args = parser.parse_args()

    notion_jobs = None
    if not args.quick:
        try:
            client = NotionClient()
            print("Fetching Notion job outcomes...", file=sys.stderr)
            notion_jobs = load_all_notion_jobs(client)
            print(f"Loaded {len(notion_jobs)} jobs from Notion", file=sys.stderr)
        except Exception as e:
            print(f"Warning: Notion query failed ({e}); falling back to local-only mode",
                  file=sys.stderr)

    intelligence = build_intelligence(notion_jobs, quick=args.quick)

    if args.dry_run:
        print(json.dumps(intelligence, indent=2))
    else:
        INTELLIGENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with INTELLIGENCE_PATH.open("w") as f:
            json.dump(intelligence, f, indent=2)
        print(f"Wrote {INTELLIGENCE_PATH}", file=sys.stderr)

    print_delta_summary(intelligence)
    return 0


if __name__ == "__main__":
    sys.exit(main())
