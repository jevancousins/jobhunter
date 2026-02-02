#!/usr/bin/env python3
"""Scrape a single job posting URL using Playwright.

Usage:
    python scripts/scrape_job.py <url>
    python scripts/scrape_job.py <url> --json

Returns the job description and metadata extracted from the page.
Uses Playwright for JavaScript-rendered pages (Lever, Greenhouse, etc.).
"""

import argparse
import json
import sys
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout


# Site-specific selectors for job descriptions
SITE_SELECTORS = {
    "lever.co": {
        "title": "h2[data-qa='posting-name'], h2.posting-headline, div.posting-headline h2",
        "description": [
            "div[data-qa='job-description']",
            "div.section-wrapper.page-full-width",
            "div.content",
            "div.posting-page",
            "div.section.page-centered",
        ],
        "location": "div.location, div.posting-categories .sort-by-time",
        "team": "div.department, div.posting-categories .department",
    },
    "greenhouse.io": {
        "title": "h1.app-title",
        "description": [
            "div#content",
            "div.job-description",
        ],
        "location": "div.location",
    },
    "blackrock.com": {
        "title": "h1.job-title, h1[data-testid='job-title']",
        "description": [
            "div.job-description",
            "div[data-testid='job-description']",
            "section.description",
        ],
        "salary": "div.salary-range, span[data-testid='salary']",
    },
    "databricks.com": {
        "title": "h1",
        "description": [
            "div.job-description",
            "div[class*='description']",
            "main",
        ],
    },
    "welcometothejungle.com": {
        "title": "h1",
        "description": [
            "div[data-testid='job-section-description']",
            "div.sc-job-description",
            "section.job-description",
        ],
    },
    # Generic fallbacks
    "default": {
        "title": "h1",
        "description": [
            "div.job-description",
            "div#job-description",
            "div[class*='description']",
            "section.description",
            "article",
            "main",
        ],
    },
}


def get_selectors_for_url(url: str) -> dict:
    """Get the appropriate selectors for a URL."""
    domain = urlparse(url).netloc.lower()

    for site, selectors in SITE_SELECTORS.items():
        if site in domain:
            return selectors

    return SITE_SELECTORS["default"]


def extract_text(page, selectors: list[str]) -> str:
    """Try multiple selectors and return first match."""
    for selector in selectors:
        try:
            elem = page.query_selector(selector)
            if elem:
                text = elem.inner_text()
                if text and len(text.strip()) > 50:  # Minimum content threshold
                    return text.strip()
        except Exception:
            continue
    return ""


def scrape_job(url: str, timeout: int = 30000) -> dict:
    """
    Scrape a job posting from any URL.

    Args:
        url: The job posting URL
        timeout: Page load timeout in milliseconds

    Returns:
        Dictionary with job details
    """
    result = {
        "url": url,
        "title": "",
        "description": "",
        "location": "",
        "salary": "",
        "error": None,
    }

    selectors = get_selectors_for_url(url)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ],
        )

        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )

        page = context.new_page()

        # Stealth settings
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
        """)

        try:
            # Navigate to page - use domcontentloaded for JS-heavy sites
            response = page.goto(url, wait_until="domcontentloaded", timeout=timeout)

            # Check for 404 or other errors
            if response and response.status >= 400:
                result["error"] = f"HTTP {response.status}"
                return result

            # Wait for dynamic content to load
            # Try networkidle with shorter timeout, fall back gracefully
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except PlaywrightTimeout:
                # Some sites never reach networkidle, that's ok
                pass

            # Additional wait for JS-rendered content
            page.wait_for_timeout(2000)

            # Extract title
            if "title" in selectors:
                title_elem = page.query_selector(selectors["title"])
                if title_elem:
                    result["title"] = title_elem.inner_text().strip()

            # Extract description
            if "description" in selectors:
                result["description"] = extract_text(page, selectors["description"])

            # Extract location
            if "location" in selectors:
                loc_elem = page.query_selector(selectors["location"])
                if loc_elem:
                    result["location"] = loc_elem.inner_text().strip()

            # Extract salary
            if "salary" in selectors:
                sal_elem = page.query_selector(selectors["salary"])
                if sal_elem:
                    result["salary"] = sal_elem.inner_text().strip()

            # Fallback: get page title if no title found
            if not result["title"]:
                result["title"] = page.title()

            # Fallback: get body text if no description found
            if not result["description"]:
                body = page.query_selector("body")
                if body:
                    result["description"] = body.inner_text()[:5000]  # Limit length

        except PlaywrightTimeout:
            result["error"] = "Timeout loading page"
        except Exception as e:
            result["error"] = str(e)
        finally:
            browser.close()

    return result


def main():
    parser = argparse.ArgumentParser(description="Scrape a job posting URL")
    parser.add_argument("url", help="Job posting URL to scrape")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--timeout", type=int, default=30000, help="Timeout in ms")

    args = parser.parse_args()

    result = scrape_job(args.url, timeout=args.timeout)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if result["error"]:
            print(f"Error: {result['error']}", file=sys.stderr)
            sys.exit(1)

        print(f"Title: {result['title']}")
        print(f"Location: {result['location']}")
        if result["salary"]:
            print(f"Salary: {result['salary']}")
        print(f"\n{'='*60}\n")
        print(result["description"])


if __name__ == "__main__":
    main()
