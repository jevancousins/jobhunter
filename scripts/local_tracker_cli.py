"""Local job tracker for JobHunter: a zero-setup alternative to Notion.

Drop-in replacement for scripts/notion_cli.py. Implements the identical
command surface and JSON output shapes, backed by a plain JSON store at
data/tracker.json. After every mutation the store is exported to
data/tracker.csv so non-technical users can review their pipeline in
Excel, Numbers or Google Sheets at any time.

Selected via data/search_config.json:

    "tracker": { "backend": "local" }

Commands (identical to notion_cli.py):
  get-job <id>                       Print JSON of a job
  list-by-status <status>            List jobs with given status
  list-watchlist-companies           List company watchlist entries
  update-status <id> <status>        Change status
  set-artefacts <id> [...]           Attach tailored CV / cover letter paths
  append-notes <id> <text>           Append to the notes field
  set-description <id> <text>        Set the job description
  create-job --payload <json>        Create a new job entry
  export                             Rewrite data/tracker.csv and print counts

The company watchlist lives in data/watchlist.json (see
data/watchlist.example.json); it is shared by both tracker backends.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STORE_PATH = ROOT / "data" / "tracker.json"
CSV_PATH = ROOT / "data" / "tracker.csv"
WATCHLIST_PATH = ROOT / "data" / "watchlist.json"

VALID_STATUSES = (
    "ToReview", "Consider", "Apply", "NeedsTailoring", "ReadyToApply",
    "Escalated", "Failed",
    "AwaitingResponse", "ResponseReceived", "PhoneScreen", "Test",
    "CultureInterview", "TechnicalInterview", "FinalRound", "Offer",
    "Expired", "NoResponse", "Rejected", "Skip", "Accepted",
)

# Column order for the human-facing CSV export.
CSV_COLUMNS = (
    "status", "title", "company", "location", "salary", "url",
    "applied_date", "source", "notes", "id",
)


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

def _load_store() -> dict:
    if not STORE_PATH.exists():
        return {"version": 1, "jobs": {}}
    try:
        return json.loads(STORE_PATH.read_text())
    except json.JSONDecodeError as e:
        raise SystemExit(
            f"data/tracker.json is corrupt ({e}). Restore it from a backup or "
            "fix the JSON by hand; refusing to overwrite it."
        )


def _save_store(store: dict) -> None:
    store["updated_at"] = datetime.now().isoformat(timespec="seconds")
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STORE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(store, indent=2))
    tmp.replace(STORE_PATH)
    _export_csv(store)


def _export_csv(store: dict) -> None:
    """Human-facing view of the pipeline; regenerated on every mutation."""
    jobs = sorted(
        store.get("jobs", {}).values(),
        key=lambda j: (j.get("status", ""), j.get("company", ""), j.get("title", "")),
    )
    with CSV_PATH.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for job in jobs:
            writer.writerow({k: job.get(k, "") or "" for k in CSV_COLUMNS})


def _summary(job: dict) -> dict:
    """Match notion_cli._page_to_summary's output shape exactly."""
    return {
        "id": job.get("id", ""),
        "title": job.get("title", ""),
        "company": job.get("company", ""),
        "location": job.get("location", ""),
        "url": job.get("url", ""),
        "status": job.get("status", ""),
        "source": job.get("source", ""),
        "salary": job.get("salary", "") or "",
        "notes": job.get("notes", "") or "",
        "description": job.get("description", "") or "",
        "tailored_cv": job.get("tailored_cv"),
        "cover_letter": job.get("cover_letter"),
    }


def _get_job_or_exit(store: dict, job_id: str) -> dict:
    job = store.get("jobs", {}).get(job_id)
    if job is None:
        raise SystemExit(f"no job with id {job_id!r} in data/tracker.json")
    return job


def _validate_status(status: str) -> str:
    if status not in VALID_STATUSES:
        raise SystemExit(
            f"invalid status {status!r}; expected one of: {', '.join(VALID_STATUSES)}"
        )
    return status


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_get_job(args) -> int:
    store = _load_store()
    print(json.dumps(_summary(_get_job_or_exit(store, args.page)), indent=2))
    return 0


def cmd_list_by_status(args) -> int:
    store = _load_store()
    results = [
        _summary(j) for j in store.get("jobs", {}).values()
        if j.get("status") == args.status
    ]
    if getattr(args, "limit", None):
        results = results[: args.limit]
    print(json.dumps(results, indent=2))
    return 0


def cmd_list_watchlist_companies(args) -> int:
    """Read the shared watchlist file (same shape as notion_cli's output)."""
    entries: list[dict] = []
    if WATCHLIST_PATH.exists():
        data = json.loads(WATCHLIST_PATH.read_text())
        raw = data.get("companies", data if isinstance(data, list) else [])
        for row in raw:
            if not isinstance(row, dict) or str(row.get("name", "")).startswith("_"):
                continue
            entry = {
                "name": row.get("name", ""),
                "careers_url": row.get("careers_url", ""),
                "priority": row.get("priority", "Medium"),
                "locations": row.get("locations", []),
                "check_daily": bool(row.get("check_daily", True)),
                "last_checked": row.get("last_checked"),
                "notes": row.get("notes"),
            }
            if args.active_only and not entry["check_daily"]:
                continue
            if entry["name"]:
                entries.append(entry)
    print(json.dumps(entries, indent=2))
    return 0


def cmd_update_status(args) -> int:
    store = _load_store()
    job = _get_job_or_exit(store, args.page)
    job["status"] = _validate_status(args.status)
    job["updated_at"] = datetime.now().isoformat(timespec="seconds")
    _save_store(store)
    print(json.dumps({"ok": True, "page_id": args.page, "status": args.status}))
    return 0


def cmd_set_artefacts(args) -> int:
    store = _load_store()
    job = _get_job_or_exit(store, args.page)
    updated = []
    if args.cv:
        job["tailored_cv"] = args.cv
        updated.append("Tailored CV")
    if args.cover_letter:
        job["cover_letter"] = args.cover_letter
        updated.append("Cover Letter")
    if getattr(args, "applied_date", None):
        job["applied_date"] = args.applied_date
        updated.append("Applied Date")
    if not updated:
        print(json.dumps({"ok": False, "error": "nothing to update"}))
        return 1
    _save_store(store)
    print(json.dumps({"ok": True, "page_id": args.page, "updated": updated}))
    return 0


def cmd_append_notes(args) -> int:
    store = _load_store()
    job = _get_job_or_exit(store, args.page)
    existing = job.get("notes") or ""
    job["notes"] = (existing + "\n" + args.text).strip() if existing else args.text
    _save_store(store)
    print(json.dumps({"ok": True, "page_id": args.page, "notes_length": len(job["notes"])}))
    return 0


def cmd_set_description(args) -> int:
    store = _load_store()
    job = _get_job_or_exit(store, args.page)
    job["description"] = args.text
    _save_store(store)
    print(json.dumps({"ok": True, "page_id": args.page, "description_length": len(args.text)}))
    return 0


def cmd_create_job(args) -> int:
    payload = (
        json.loads(Path(args.json_file).read_text()) if args.json_file
        else json.loads(args.payload)
    )
    store = _load_store()
    seed = f"{payload.get('company', '')}_{payload['title']}_{payload['url']}"
    job_id = "local-" + hashlib.md5(seed.encode()).hexdigest()[:12]
    if job_id in store.get("jobs", {}):
        print(json.dumps({
            "ok": True, "page_id": job_id,
            "title": payload["title"], "existing": True,
        }))
        return 0
    now = datetime.now().isoformat(timespec="seconds")
    store.setdefault("jobs", {})[job_id] = {
        "id": job_id,
        "title": payload["title"],
        "company": payload.get("company", ""),
        "location": payload.get("location", ""),
        "url": payload["url"],
        "status": _validate_status(payload.get("status", "ToReview")),
        "source": payload.get("source", "LinkedIn"),
        "salary": payload.get("salary"),
        "notes": payload.get("notes", ""),
        "description": payload.get("description", ""),
        "created_at": now,
        "updated_at": now,
    }
    _save_store(store)
    print(json.dumps({"ok": True, "page_id": job_id, "title": payload["title"]}))
    return 0


def cmd_export(args) -> int:
    store = _load_store()
    _export_csv(store)
    counts: dict[str, int] = {}
    for job in store.get("jobs", {}).values():
        counts[job.get("status", "?")] = counts.get(job.get("status", "?"), 0) + 1
    print(json.dumps({
        "ok": True,
        "csv": str(CSV_PATH.relative_to(ROOT)),
        "total": len(store.get("jobs", {})),
        "by_status": dict(sorted(counts.items())),
    }, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Local tracker CLI for JobHunter")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_get = sub.add_parser("get-job")
    p_get.add_argument("page")
    p_get.set_defaults(func=cmd_get_job)

    p_list = sub.add_parser("list-by-status")
    p_list.add_argument("status")
    p_list.add_argument("--limit", type=int, default=None)
    p_list.set_defaults(func=cmd_list_by_status)

    p_watchlist = sub.add_parser("list-watchlist-companies")
    p_watchlist.add_argument("--active-only", action="store_true")
    p_watchlist.set_defaults(func=cmd_list_watchlist_companies)

    p_upd = sub.add_parser("update-status")
    p_upd.add_argument("page")
    p_upd.add_argument("status")
    p_upd.set_defaults(func=cmd_update_status)

    p_art = sub.add_parser("set-artefacts")
    p_art.add_argument("page")
    p_art.add_argument("--cv")
    p_art.add_argument("--cover-letter")
    p_art.add_argument("--applied-date")
    p_art.set_defaults(func=cmd_set_artefacts)

    p_note = sub.add_parser("append-notes")
    p_note.add_argument("page")
    p_note.add_argument("text")
    p_note.set_defaults(func=cmd_append_notes)

    p_desc = sub.add_parser("set-description")
    p_desc.add_argument("page")
    p_desc.add_argument("text")
    p_desc.set_defaults(func=cmd_set_description)

    p_create = sub.add_parser("create-job")
    p_create.add_argument("--json-file")
    p_create.add_argument("--payload")
    p_create.set_defaults(func=cmd_create_job)

    p_export = sub.add_parser("export")
    p_export.set_defaults(func=cmd_export)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
