#!/usr/bin/env python3
"""Render Lens benchmark reports as self-contained HTML.

Usage::

    # Single report
    python bench/tools/report.py render bench/reports/run.json

    # Compare multiple reports side-by-side
    python bench/tools/report.py compare bench/reports/a.json bench/reports/b.json

Output is written next to the input JSON (``run.html``) or to ``--output``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_TEMPLATE = Path(__file__).parent / "report_template.html"


def _render_html(report_json: str, output_path: Path) -> None:
    """Inject *report_json* into the HTML template and write to *output_path*."""
    template = _TEMPLATE.read_text(encoding="utf-8")
    html = template.replace("__REPORT_JSON__", report_json)
    output_path.write_text(html, encoding="utf-8")
    print(f"Report written to {output_path}")


def cmd_render(args: argparse.Namespace) -> None:
    """Render a single report JSON to HTML."""
    input_path = Path(args.input)
    data = json.loads(input_path.read_text(encoding="utf-8"))
    output = Path(args.output) if args.output else input_path.with_suffix(".html")
    _render_html(json.dumps(data, ensure_ascii=False), output)


def cmd_compare(args: argparse.Namespace) -> None:
    """Render a comparison of multiple report JSONs to HTML."""
    reports: list[dict[str, object]] = []
    for p in args.inputs:
        reports.append(json.loads(Path(p).read_text(encoding="utf-8")))
    if len(reports) < 2:
        print("Need at least 2 reports to compare.", file=sys.stderr)
        raise SystemExit(1)

    output = Path(args.output) if args.output else Path(args.inputs[0]).with_name("comparison.html")
    _render_html(json.dumps(reports, ensure_ascii=False), output)


def main() -> None:
    parser = argparse.ArgumentParser(description="Lens benchmark report renderer")
    sub = parser.add_subparsers(dest="command")

    render_p = sub.add_parser("render", help="Render a single report to HTML")
    render_p.add_argument("input", help="Path to report JSON")
    render_p.add_argument("-o", "--output", help="Output HTML path (default: same name, .html)")

    compare_p = sub.add_parser("compare", help="Compare multiple reports side-by-side")
    compare_p.add_argument("inputs", nargs="+", help="Paths to report JSONs")
    compare_p.add_argument("-o", "--output", help="Output HTML path (default: comparison.html)")

    args = parser.parse_args()
    if args.command == "render":
        cmd_render(args)
    elif args.command == "compare":
        cmd_compare(args)
    else:
        parser.print_help()
        raise SystemExit(1)


if __name__ == "__main__":
    main()
