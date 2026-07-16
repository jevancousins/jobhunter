#!/usr/bin/env python3
"""Measure line count and last-line fill of CV bullets rendered in LaTeX.

Generates a multi-page LaTeX file (one bullet per page), compiles once,
then uses PyMuPDF to measure each page.

Usage:
    # Measure all bullets in master_cv.json
    python scripts/check_bullet_fill.py

    # Measure a single bullet text
    python scripts/check_bullet_fill.py --text "Automated the reporting pipeline, saving 200+ hours a year"

    # Validate versions already in master_cv.json
    python scripts/check_bullet_fill.py --validate

Exit codes: 0 = all pass, 1 = failures found, 2 = build error
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile

import fitz  # PyMuPDF

# Layout constants matching cv.cls
A4_WIDTH = 595.28
LEFT_MARGIN = 0.5 * 72   # 36pt
RIGHT_MARGIN = 0.5 * 72  # 36pt
CONTENT_WIDTH = A4_WIDTH - LEFT_MARGIN - RIGHT_MARGIN  # ~523.3pt
ITEMIZE_INDENT = 1.2 * 10  # 1.2em at 10pt base ~ 12pt
BULLET_TEXT_WIDTH = CONTENT_WIDTH - ITEMIZE_INDENT  # ~511pt

# Fill thresholds
SHORT_MIN_FILL = 85.0   # 1-line bullets must fill >= 85% of the line
MEDIUM_LONG_MIN_FILL = 50.0  # last line of 2-3 line bullets must fill >= 50%

LATEX_TEMPLATE = r"""\documentclass{{cv}}
\begin{{document}}
{pages}
\end{{document}}
"""

BULLET_PAGE = r"""
\begin{{itemize}}
\cvbullet{{{text}}}
\end{{itemize}}
\newpage
"""

PROJECT_PAGE = r"""
{{\small\textbf{{{name}}} -- {text}}}
\newpage
"""


def escape_latex(text: str) -> str:
    """Escape characters that are special in LaTeX."""
    text = text.replace("&", r"\&")
    text = text.replace("%", r"\%")
    text = text.replace("#", r"\#")
    text = text.replace("_", r"\_")
    text = text.replace("~", r"\textasciitilde{}")
    text = text.replace("—", "---")  # em-dash
    text = text.replace("–", "--")   # en-dash
    return text


def generate_latex(items: list[dict]) -> str:
    """Generate a multi-page LaTeX document with one item per page."""
    pages = []
    for item in items:
        text = escape_latex(item["text"])
        if item.get("type") == "project":
            name = escape_latex(item["name"])
            pages.append(PROJECT_PAGE.format(name=name, text=text))
        else:
            pages.append(BULLET_PAGE.format(text=text))
    return LATEX_TEMPLATE.format(pages="".join(pages))


def compile_latex(latex_src: str, work_dir: str) -> str:
    """Compile LaTeX source and return path to PDF."""
    tex_path = os.path.join(work_dir, "bullets.tex")
    pdf_path = os.path.join(work_dir, "bullets.pdf")

    with open(tex_path, "w") as f:
        f.write(latex_src)

    env = os.environ.copy()
    env["PATH"] = f"/Library/TeX/texbin:{env.get('PATH', '')}"

    # cv.cls lives in cv/ so we need TEXINPUTS to find it
    cv_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "cv")
    env["TEXINPUTS"] = f"{cv_dir}:{work_dir}:"

    result = subprocess.run(
        ["pdflatex", "-interaction=nonstopmode", "-output-directory", work_dir, tex_path],
        capture_output=True, text=True, env=env, timeout=60,
    )

    if not os.path.exists(pdf_path):
        print("LaTeX compilation failed:", file=sys.stderr)
        print(result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout, file=sys.stderr)
        return None

    return pdf_path


def measure_page(page) -> dict:
    """Measure line count and last-line fill for a single page's content."""
    text_dict = page.get_text("dict")
    content_lines = []

    for block in text_dict.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            text = "".join(s.get("text", "") for s in spans).strip()
            if not text:
                continue
            bbox = line.get("bbox")
            line_width = bbox[2] - bbox[0]
            fill_pct = (line_width / CONTENT_WIDTH) * 100
            content_lines.append({
                "text": text,
                "width": line_width,
                "fill_pct": round(fill_pct, 1),
                "y": bbox[1],
            })

    if not content_lines:
        return {"lines": 0, "last_line_fill": 0.0, "all_lines": []}

    return {
        "lines": len(content_lines),
        "last_line_fill": content_lines[-1]["fill_pct"],
        "first_line_fill": content_lines[0]["fill_pct"],
        "all_lines": content_lines,
    }


def check_fill(lines: int, last_fill: float) -> tuple[bool, str]:
    """Check if a bullet meets fill constraints for its line count."""
    if lines == 1:
        ok = last_fill >= SHORT_MIN_FILL
        label = "short"
        threshold = SHORT_MIN_FILL
    elif lines == 2:
        ok = last_fill >= MEDIUM_LONG_MIN_FILL
        label = "medium"
        threshold = MEDIUM_LONG_MIN_FILL
    elif lines == 3:
        ok = last_fill >= MEDIUM_LONG_MIN_FILL
        label = "long"
        threshold = MEDIUM_LONG_MIN_FILL
    else:
        ok = False
        label = f"overflow({lines})"
        threshold = 0
    return ok, label, threshold


def collect_bullets(data: dict) -> list[dict]:
    """Extract all bullets from master_cv.json."""
    items = []
    for exp in data.get("experience", []):
        company = exp.get("company", "?")
        for i, bullet in enumerate(exp.get("bullets", [])):
            items.append({
                "id": f"exp:{company}:{i}",
                "text": bullet["text"],
                "type": "bullet",
                "source": company,
            })

    for key, proj in data.get("projects", {}).items():
        if isinstance(proj, dict):
            for field in ["summary_short", "summary_medium"]:
                if field in proj:
                    items.append({
                        "id": f"proj:{key}:{field}",
                        "text": proj[field],
                        "name": proj.get("display_name", proj.get("name", key)),
                        "type": "project",
                        "source": key,
                    })

    return items


def collect_versioned_bullets(data: dict) -> list[dict]:
    """Extract all versioned bullets for validation."""
    items = []
    for exp in data.get("experience", []):
        company = exp.get("company", "?")
        for i, bullet in enumerate(exp.get("bullets", [])):
            versions = bullet.get("versions", {})
            for ver_name, ver_text in versions.items():
                expected_lines = {"short": 1, "medium": 2, "long": 3}.get(ver_name)
                items.append({
                    "id": f"exp:{company}:{i}:{ver_name}",
                    "text": ver_text,
                    "type": "bullet",
                    "source": company,
                    "version": ver_name,
                    "expected_lines": expected_lines,
                })

    for key, proj in data.get("projects", {}).items():
        if isinstance(proj, dict) and "versions" in proj:
            for ver_name, ver_text in proj["versions"].items():
                expected_lines = {"short": 1, "medium": 2, "long": 3}.get(ver_name)
                items.append({
                    "id": f"proj:{key}:{ver_name}",
                    "text": ver_text,
                    "name": proj.get("display_name", proj.get("name", key)),
                    "type": "project",
                    "source": key,
                    "version": ver_name,
                    "expected_lines": expected_lines,
                })

    return items


def main():
    parser = argparse.ArgumentParser(description="Measure CV bullet line fill.")
    parser.add_argument("--text", help="Measure a single bullet text")
    parser.add_argument("--project", nargs=2, metavar=("NAME", "TEXT"),
                        help="Measure a single project description")
    parser.add_argument("--validate", action="store_true",
                        help="Validate all versioned bullets in master_cv.json")
    parser.add_argument("--json", action="store_true", dest="as_json",
                        help="Output as JSON")
    args = parser.parse_args()

    master_cv_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "data", "master_cv.json"
    )

    if not (args.text or args.project) and not os.path.exists(master_cv_path):
        print(
            "data/master_cv.json not found. Run /onboard to generate it, or "
            "copy data/master_cv.example.json and fill it in.",
            file=sys.stderr,
        )
        sys.exit(2)

    if args.text:
        items = [{"id": "cli:0", "text": args.text, "type": "bullet"}]
    elif args.project:
        items = [{"id": "cli:0", "text": args.project[1], "name": args.project[0], "type": "project"}]
    elif args.validate:
        with open(master_cv_path) as f:
            data = json.load(f)
        items = collect_versioned_bullets(data)
        if not items:
            print("No versioned bullets found in master_cv.json")
            sys.exit(0)
    else:
        with open(master_cv_path) as f:
            data = json.load(f)
        items = collect_bullets(data)

    if not items:
        print("No items to measure")
        sys.exit(0)

    latex_src = generate_latex(items)

    with tempfile.TemporaryDirectory() as tmpdir:
        # Copy cv.cls and sections/ to tmpdir so pdflatex can find them
        cv_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "cv")

        pdf_path = compile_latex(latex_src, tmpdir)
        if not pdf_path:
            sys.exit(2)

        doc = fitz.open(pdf_path)
        results = []
        failures = 0

        for i, item in enumerate(items):
            if i >= len(doc):
                break
            measurement = measure_page(doc[i])
            lines = measurement["lines"]
            last_fill = measurement["last_line_fill"]
            ok, label, threshold = check_fill(lines, last_fill)

            # For validation mode, also check expected line count
            if args.validate and "expected_lines" in item:
                expected = item["expected_lines"]
                if lines != expected:
                    ok = False
                    label = f"{item['version']}(expected {expected} lines, got {lines})"

            result = {
                "id": item["id"],
                "lines": lines,
                "last_line_fill": last_fill,
                "label": label,
                "pass": ok,
                "threshold": threshold,
            }
            results.append(result)
            if not ok:
                failures += 1

        doc.close()

    if args.as_json:
        print(json.dumps(results, indent=2))
    else:
        for r in results:
            status = "PASS" if r["pass"] else "FAIL"
            print(f"[{status}] {r['id']}: {r['lines']} lines, "
                  f"last line {r['last_line_fill']:.1f}% "
                  f"(need {r['threshold']:.0f}%) -> {r['label']}")

        print(f"\n{len(results)} items: {len(results) - failures} pass, {failures} fail")

    sys.exit(1 if failures > 0 else 0)


if __name__ == "__main__":
    main()
