#!/usr/bin/env python3
"""Check page fill of a single-page CV PDF.

Uses PyMuPDF to measure the gap between the lowest content on page 1
and the bottom of the content area. Returns FULL, UNDERFILLED, or OVERFLOW.

Usage:
    python scripts/check_page_fill.py <pdf_path> [--threshold 15]

Exit codes: 0=FULL, 1=UNDERFILLED, 2=OVERFLOW
"""

import argparse
import json
import sys

import fitz  # PyMuPDF


# A4 dimensions in points
A4_HEIGHT = 841.89
# 0.4in bottom margin (matching cv.cls) = 0.4 * 72 = 28.8pt
BOTTOM_MARGIN = 28.8
CONTENT_AREA_BOTTOM = A4_HEIGHT - BOTTOM_MARGIN  # ~813.1pt


def check_page_fill(pdf_path: str, threshold: float = 15.0) -> dict:
    """Analyse page fill of a CV PDF.

    Args:
        pdf_path: Path to the PDF file.
        threshold: Gap in points below which the page is considered FULL.
                   Default 15pt is approximately one line of text.

    Returns:
        Dict with keys: pages, content_bottom, page_bottom, gap, status, lines_estimate
    """
    doc = fitz.open(pdf_path)
    pages = len(doc)

    if pages > 1:
        doc.close()
        return {
            "pages": pages,
            "content_bottom": None,
            "page_bottom": round(CONTENT_AREA_BOTTOM, 1),
            "gap": None,
            "status": "OVERFLOW",
            "lines_estimate": None,
        }

    page = doc[0]
    content_bottom = 0.0

    # Check text blocks
    text_dict = page.get_text("dict")
    for block in text_dict.get("blocks", []):
        bbox = block.get("bbox")
        if bbox:
            content_bottom = max(content_bottom, bbox[3])  # y1 = bottom of block

    # Check drawings (rules, lines drawn by LaTeX e.g. \titlerule)
    for drawing in page.get_drawings():
        for item in drawing.get("items", []):
            # Each item is a tuple like ("l", Point, Point) for lines
            # or ("re", Rect) for rectangles, etc.
            if item[0] == "l":  # line
                content_bottom = max(content_bottom, item[1].y, item[2].y)
            elif item[0] == "re":  # rectangle
                content_bottom = max(content_bottom, item[1].y1)
            elif item[0] == "c":  # curve (4 points)
                for pt in item[1:]:
                    if hasattr(pt, "y"):
                        content_bottom = max(content_bottom, pt.y)

    doc.close()

    gap = CONTENT_AREA_BOTTOM - content_bottom
    lines_estimate = max(0, int(gap / 12))  # ~12pt per line

    if gap <= threshold:
        status = "FULL"
    else:
        status = "UNDERFILLED"

    return {
        "pages": 1,
        "content_bottom": round(content_bottom, 1),
        "page_bottom": round(CONTENT_AREA_BOTTOM, 1),
        "gap": round(gap, 1),
        "status": status,
        "lines_estimate": lines_estimate if status == "UNDERFILLED" else None,
    }


def main():
    parser = argparse.ArgumentParser(description="Check CV PDF page fill.")
    parser.add_argument("pdf_path", help="Path to the PDF file")
    parser.add_argument(
        "--threshold",
        type=float,
        default=15.0,
        help="Gap threshold in points (default: 15, approx 1 line)",
    )
    parser.add_argument(
        "--json", action="store_true", dest="as_json", help="Output as JSON"
    )
    args = parser.parse_args()

    result = check_page_fill(args.pdf_path, args.threshold)

    if args.as_json:
        print(json.dumps(result))
    else:
        parts = [f"Pages: {result['pages']}"]
        if result["status"] == "OVERFLOW":
            parts.append("Fill: OVERFLOW")
        else:
            parts.extend([
                f"Content bottom: {result['content_bottom']}pt",
                f"Page bottom: {result['page_bottom']}pt",
                f"Gap: {result['gap']}pt",
                f"Fill: {result['status']}",
            ])
            if result["lines_estimate"]:
                parts.append(f"(~{result['lines_estimate']} lines to fill)")
        print(" | ".join(parts))

    # Exit codes: 0=FULL, 1=UNDERFILLED, 2=OVERFLOW
    if result["status"] == "FULL":
        sys.exit(0)
    elif result["status"] == "UNDERFILLED":
        sys.exit(1)
    else:
        sys.exit(2)


if __name__ == "__main__":
    main()
