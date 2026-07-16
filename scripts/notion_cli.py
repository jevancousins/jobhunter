"""Notion CLI helper for the auto-apply pipeline.

Self-contained: all Notion and model logic is inlined here so there is no
dependency on the old src/ package.

Commands:
  get-job <page-id-or-url>           Print JSON of a job
  list-by-status <status>            List jobs with given status
  list-watchlist-companies           List active Company Watchlist names
  update-status <page-id> <status>   Change status
  set-artefacts <page-id> [...]      Attach tailored CV / cover letter URLs
  append-notes <page-id> <text>      Append to Notes field
  set-description <page-id> <text>   Set the Description field (from JD)
  create-job --payload <json>        Create a new job entry

All outputs are JSON on stdout for easy parsing.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from notion_client import Client
from tenacity import retry, stop_after_attempt, wait_exponential

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


# ---------------------------------------------------------------------------
# Models (inlined from former src/models.py, stripped to what's actually used)
# ---------------------------------------------------------------------------

class JobStatus(Enum):
    TO_REVIEW = "ToReview"
    CONSIDER = "Consider"
    APPLY = "Apply"
    NEEDS_TAILORING = "NeedsTailoring"
    READY_TO_APPLY = "ReadyToApply"
    ESCALATED = "Escalated"
    FAILED = "Failed"
    AWAITING_RESPONSE = "AwaitingResponse"
    RESPONSE_RECEIVED = "ResponseReceived"
    PHONE_SCREEN = "PhoneScreen"
    TEST = "Test"
    CULTURE_INTERVIEW = "CultureInterview"
    TECHNICAL_INTERVIEW = "TechnicalInterview"
    FINAL_ROUND = "FinalRound"
    OFFER = "Offer"
    EXPIRED = "Expired"
    NO_RESPONSE = "NoResponse"
    REJECTED = "Rejected"
    SKIP = "Skip"
    ACCEPTED = "Accepted"
    # Legacy aliases
    NEW = "ToReview"
    REVIEWING = "Consider"
    APPLIED = "AwaitingResponse"
    INTERVIEW = "PhoneScreen"
    PASS = "Skip"


class JobSource(Enum):
    LINKEDIN = "LinkedIn"
    INDEED = "Indeed"
    WTFJ = "Welcome to the Jungle"
    COMPANY_PAGE = "Company Page"
    GLASSDOOR = "Glassdoor"


@dataclass
class Job:
    title: str
    company: str
    location: str
    description: str
    url: str
    source: JobSource
    id: str = ""
    posted_date: Optional[datetime] = None
    discovered_date: datetime = field(default_factory=datetime.now)
    salary: Optional[str] = None
    status: JobStatus = JobStatus.NEW
    notes: Optional[str] = None

    def __post_init__(self):
        if not self.id:
            import hashlib
            hash_input = f"{self.company}_{self.title}_{self.url}"
            self.id = hashlib.md5(hash_input.encode()).hexdigest()[:12]


@dataclass
class Company:
    name: str
    careers_url: str
    priority: str = "Medium"
    locations: list[str] = field(default_factory=list)
    check_daily: bool = True
    last_checked: Optional[datetime] = None
    notes: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "careers_url": self.careers_url,
            "priority": self.priority,
            "locations": self.locations,
            "check_daily": self.check_daily,
            "last_checked": self.last_checked.isoformat() if self.last_checked else None,
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# Notion helpers (inlined from former src/notion/client.py)
# ---------------------------------------------------------------------------

_NOTION_BLOCK_LIMIT = 2000


def _notion_text_length(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def _rich_text(text: str) -> list[dict]:
    if not text:
        return []
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for char in text:
        char_len = _notion_text_length(char)
        if current and current_len + char_len > _NOTION_BLOCK_LIMIT:
            chunks.append("".join(current))
            current = []
            current_len = 0
        current.append(char)
        current_len += char_len
    if current:
        chunks.append("".join(current))
    return [{"text": {"content": chunk}} for chunk in chunks]


def _notion_plain_text(items: list[dict]) -> str:
    return "".join(
        item.get("plain_text") or item.get("text", {}).get("content", "")
        for item in items
    )


class NotionClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        jobs_db_id: Optional[str] = None,
        companies_db_id: Optional[str] = None,
    ):
        self.api_key = api_key or os.environ.get("NOTION_API_KEY", "")
        self.jobs_db_id = jobs_db_id or os.environ.get("NOTION_JOBS_DB_ID", "")
        self.companies_db_id = companies_db_id or os.environ.get("NOTION_COMPANIES_DB_ID", "")
        self.client = Client(auth=self.api_key)
        self._ds_cache: dict[str, str] = {}

    def _data_source_id_for(self, database_id: str) -> str:
        if database_id in self._ds_cache:
            return self._ds_cache[database_id]
        db = self.client.databases.retrieve(database_id=database_id)
        sources = db.get("data_sources") or []
        if not sources:
            raise RuntimeError(f"database {database_id} has no data_sources")
        ds_id = sources[0]["id"]
        self._ds_cache[database_id] = ds_id
        return ds_id

    @retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=1, min=2, max=15))
    def query_database(self, database_id: str, **kwargs: Any) -> dict:
        kwargs.pop("database_id", None)
        kwargs.pop("data_source_id", None)
        ds_id = self._data_source_id_for(database_id)
        return self.client.data_sources.query(data_source_id=ds_id, **kwargs)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def create_job(self, job: Job) -> str:
        properties = self._job_to_properties(job)
        response = self.client.pages.create(
            parent={"database_id": self.jobs_db_id},
            properties=properties,
        )
        return response["id"]

    def _job_to_properties(self, job: Job) -> dict[str, Any]:
        properties: dict[str, Any] = {
            "Title": {"title": _rich_text(job.title)},
            "Company": {"rich_text": _rich_text(job.company)},
            "Location": {"select": {"name": job.location}} if job.location else {"select": None},
            "Status": {"status": {"name": job.status.value}},
            "Source": {"select": {"name": job.source.value}},
            "URL": {"url": job.url},
            "Discovered Date": {"date": {"start": job.discovered_date.isoformat()}},
        }
        if job.posted_date:
            properties["Posted Date"] = {"date": {"start": job.posted_date.isoformat()}}
        if job.salary:
            properties["Salary"] = {"rich_text": _rich_text(job.salary)}
        if job.description:
            properties["Job Description"] = {"rich_text": _rich_text(job.description)}
        if job.notes:
            properties["Notes"] = {"rich_text": _rich_text(job.notes)}
        return properties

    def get_companies_to_check(self) -> list[Company]:
        companies = []
        cursor = None
        while True:
            kwargs: dict[str, Any] = {
                "filter": {"property": "Check Daily", "checkbox": {"equals": True}},
                "page_size": 100,
            }
            if cursor:
                kwargs["start_cursor"] = cursor
            response = self.query_database(self.companies_db_id, **kwargs)
            for page in response["results"]:
                try:
                    companies.append(self._page_to_company(page))
                except Exception:
                    pass
            if not response.get("has_more"):
                break
            cursor = response.get("next_cursor")
        return companies

    def _page_to_company(self, page: dict) -> Company:
        props = page["properties"]
        name = ""
        if props.get("Name", {}).get("title"):
            name = props["Name"]["title"][0]["text"]["content"]
        careers_url = props.get("Careers URL", {}).get("url", "")
        priority = "Medium"
        if props.get("Priority", {}).get("select"):
            priority = props["Priority"]["select"]["name"]
        locations = []
        if props.get("Locations", {}).get("multi_select"):
            locations = [loc["name"] for loc in props["Locations"]["multi_select"]]
        check_daily = props.get("Check Daily", {}).get("checkbox", True)
        last_checked = None
        if props.get("Last Checked", {}).get("date"):
            last_checked = datetime.fromisoformat(props["Last Checked"]["date"]["start"])
        notes = ""
        if props.get("Notes", {}).get("rich_text"):
            notes = _notion_plain_text(props["Notes"]["rich_text"])
        return Company(
            name=name, careers_url=careers_url, priority=priority,
            locations=locations, check_daily=check_daily,
            last_checked=last_checked, notes=notes,
        )


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------

def _extract_page_id(value: str) -> str:
    if value.startswith("http"):
        last = value.rstrip("/").split("/")[-1]
        token = last.split("?")[0].split("-")[-1]
        if len(token) == 32:
            return f"{token[0:8]}-{token[8:12]}-{token[12:16]}-{token[16:20]}-{token[20:32]}"
        return token
    return value


def _page_to_summary(page: dict) -> dict:
    props = page.get("properties", {})

    def _text(f: str) -> str:
        p = props.get(f, {})
        if p.get("rich_text"):
            return "".join(t.get("plain_text", "") for t in p["rich_text"])
        if p.get("title"):
            return "".join(t.get("plain_text", "") for t in p["title"])
        return ""

    def _select(f: str) -> str:
        p = props.get(f, {})
        if p.get("select"):
            return p["select"].get("name", "")
        if p.get("status"):
            return p["status"].get("name", "")
        return ""

    return {
        "id": page["id"],
        "title": _text("Title"),
        "company": _text("Company"),
        "location": _select("Location") or _text("Location"),
        "url": props.get("URL", {}).get("url", ""),
        "status": _select("Status"),
        "source": _select("Source"),
        "salary": _text("Salary"),
        "notes": _text("Notes"),
        "description": _text("Job Description"),
        "tailored_cv": props.get("Tailored CV", {}).get("url"),
        "cover_letter": props.get("Cover Letter", {}).get("url"),
    }


def cmd_get_job(args) -> int:
    client = NotionClient()
    page_id = _extract_page_id(args.page)
    page = client.client.pages.retrieve(page_id=page_id)
    print(json.dumps(_page_to_summary(page), indent=2))
    return 0


def cmd_list_by_status(args) -> int:
    client = NotionClient()
    results = []
    cursor = None
    while True:
        kwargs: dict[str, Any] = {
            "filter": {"property": "Status", "status": {"equals": args.status}},
            "page_size": 100,
        }
        if cursor:
            kwargs["start_cursor"] = cursor
        response = client.query_database(client.jobs_db_id, **kwargs)
        results.extend([_page_to_summary(p) for p in response["results"]])
        if not response.get("has_more"):
            break
        cursor = response.get("next_cursor")
    if hasattr(args, "limit") and args.limit:
        results = results[: args.limit]
    print(json.dumps(results, indent=2))
    return 0


def cmd_list_watchlist_companies(args) -> int:
    client = NotionClient()
    if args.active_only:
        companies = client.get_companies_to_check()
        results = [c.to_dict() for c in companies]
    else:
        results = []
        cursor = None
        while True:
            kwargs: dict[str, Any] = {"page_size": 100}
            if cursor:
                kwargs["start_cursor"] = cursor
            response = client.query_database(client.companies_db_id, **kwargs)
            for page in response["results"]:
                company = client._page_to_company(page)
                results.append(company.to_dict())
            if not response.get("has_more"):
                break
            cursor = response.get("next_cursor")
    print(json.dumps(results, indent=2))
    return 0


def cmd_update_status(args) -> int:
    client = NotionClient()
    page_id = _extract_page_id(args.page)
    client.client.pages.update(
        page_id=page_id,
        properties={"Status": {"status": {"name": args.status}}},
    )
    print(json.dumps({"ok": True, "page_id": page_id, "status": args.status}))
    return 0


def cmd_set_artefacts(args) -> int:
    client = NotionClient()
    page_id = _extract_page_id(args.page)
    properties: dict = {}
    if args.cv:
        properties["Tailored CV"] = {"url": args.cv}
    if args.cover_letter:
        properties["Cover Letter"] = {"url": args.cover_letter}
    if getattr(args, "applied_date", None):
        properties["Applied Date"] = {"date": {"start": args.applied_date}}
    if not properties:
        print(json.dumps({"ok": False, "error": "nothing to update"}))
        return 1
    @retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=1, min=2, max=15))
    def _do_update() -> None:
        client.client.pages.update(page_id=page_id, properties=properties)

    _do_update()
    print(json.dumps({"ok": True, "page_id": page_id, "updated": list(properties)}))
    return 0


def cmd_append_notes(args) -> int:
    client = NotionClient()
    page_id = _extract_page_id(args.page)
    page = client.client.pages.retrieve(page_id=page_id)
    existing = ""
    notes_prop = page.get("properties", {}).get("Notes", {})
    if notes_prop.get("rich_text"):
        existing = "".join(t.get("plain_text", "") for t in notes_prop["rich_text"])
    new_notes = (existing + "\n" + args.text).strip() if existing else args.text
    client.client.pages.update(
        page_id=page_id,
        properties={"Notes": {"rich_text": _rich_text(new_notes)}},
    )
    print(json.dumps({"ok": True, "page_id": page_id, "notes_length": len(new_notes)}))
    return 0


def cmd_set_description(args) -> int:
    client = NotionClient()
    page_id = _extract_page_id(args.page)
    client.client.pages.update(
        page_id=page_id,
        properties={"Job Description": {"rich_text": _rich_text(args.text)}},
    )
    print(json.dumps({"ok": True, "page_id": page_id, "description_length": len(args.text)}))
    return 0


def cmd_create_job(args) -> int:
    client = NotionClient()
    payload = json.loads(Path(args.json_file).read_text()) if args.json_file else json.loads(args.payload)
    job = Job(
        title=payload["title"],
        company=payload.get("company", ""),
        location=payload.get("location", ""),
        description=payload.get("description", ""),
        url=payload["url"],
        source=JobSource(payload.get("source", "LinkedIn")),
        status=JobStatus(payload.get("status", "ToReview")),
        notes=payload.get("notes", ""),
        salary=payload.get("salary"),
    )
    page_id = client.create_job(job)
    print(json.dumps({"ok": True, "page_id": page_id, "title": job.title}))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Notion CLI for JobHunter")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_get = sub.add_parser("get-job")
    p_get.add_argument("page")
    p_get.set_defaults(func=cmd_get_job)

    p_list = sub.add_parser("list-by-status")
    p_list.add_argument("status")
    p_list.add_argument("--limit", type=int, default=None)
    p_list.set_defaults(func=cmd_list_by_status)

    p_watchlist = sub.add_parser("list-watchlist-companies")
    p_watchlist.add_argument(
        "--active-only", action="store_true",
        help="Only return Company Watchlist rows with Check Daily enabled.",
    )
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
    p_create.add_argument("--json-file", help="Path to JSON with job data")
    p_create.add_argument("--payload", help="Inline JSON instead of file")
    p_create.set_defaults(func=cmd_create_job)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
