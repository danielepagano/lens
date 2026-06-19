#!/usr/bin/env python3
"""Render Lens benchmark reports as self-contained HTML.

Usage::

    # Create a new report JSON + HTML skeleton (after setup_bench, when you know PROJECT)
    python bench/tools/report.py init \\
        --scenario bench/scenarios/edit_quality.md \\
        --profile deepseek \\
        --project-dir bench/projects/lens_bench_abc123

    # Merge a patch (steps, evaluation, meta) into an existing report — re-renders HTML
    python bench/tools/report.py merge bench/reports/run.json --patch step_out.json
    # or: python bench/tools/report.py merge bench/reports/run.json < patch.json

    # Validate a completed report (optional: cross-check step IDs vs scenario)
    python bench/tools/report.py validate bench/reports/run.json \\
        --scenario bench/scenarios/edit_quality.md

    # Re-render JSON → HTML (after hand-editing JSON)
    python bench/tools/report.py render bench/reports/run.json

    # Re-render only if JSON is newer than HTML (fixes stale HTML)
    python bench/tools/report.py sync bench/reports/run.json

    # Compare multiple reports side-by-side (paths relative to repo root work)
    python bench/tools/report.py compare bench/reports/a.json bench/reports/b.json

Output is written next to the input JSON (``run.html``) or to ``--output``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_TEMPLATE = Path(__file__).parent / "report_template.html"


def _resolve_under_repo(path_str: str) -> Path:
    """Resolve *path_str* relative to the repository root when not absolute."""
    p = Path(path_str)
    if p.is_absolute():
        return p.resolve()
    return (_REPO_ROOT / p).resolve()


def _scenario_step_ids(scenario_path: Path) -> list[str]:
    """Return step IDs from the ``## Steps`` section (``### `id` `` headings)."""
    text = scenario_path.read_text(encoding="utf-8")
    m = re.search(r"^## Steps\s*$", text, re.MULTILINE)
    if not m:
        return []
    rest = text[m.end() :]
    m2 = re.search(r"^## [^#]", rest, re.MULTILINE)
    chunk = rest[: m2.start()] if m2 else rest
    return re.findall(r"^### `([^`]+)`", chunk, re.MULTILINE)


def _scenario_title_and_id(scenario_path: Path) -> tuple[str, str]:
    text = scenario_path.read_text(encoding="utf-8")
    scenario_id = scenario_path.stem
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip(), scenario_id
    return scenario_id.replace("_", " ").title(), scenario_id


def _resolve_profile_path(repo_root: Path, profile: str) -> Path:
    p = Path(profile)
    if p.is_absolute() and p.exists():
        return p
    if p.exists():
        return p.resolve()
    candidate = repo_root / "bench" / "llm_profiles" / f"{profile.removesuffix('.toml')}.toml"
    if candidate.exists():
        return candidate
    raise SystemExit(f"LLM profile not found: {profile}")


def _load_llm_meta(profile_path: Path) -> tuple[str, str]:
    with profile_path.open("rb") as fh:
        data = tomllib.load(fh)
    llm = data.get("llm")
    if not isinstance(llm, dict):
        return profile_path.stem, ""
    llm_d = cast(dict[str, Any], llm)
    model = llm_d.get("model")
    return profile_path.stem, model if isinstance(model, str) else ""


def _apply_report_patch(base: dict[str, Any], patch: dict[str, Any]) -> None:
    """Merge *patch* into *base* in place (meta keys merged; other keys replaced)."""
    for key, val in patch.items():
        if key == "meta" and isinstance(val, dict):
            meta = base.setdefault("meta", {})
            if not isinstance(meta, dict):
                raise SystemExit("Invalid report: meta must be an object")
            cast(dict[str, Any], meta).update(cast(dict[str, Any], val))
        else:
            base[key] = val


def cmd_merge(args: argparse.Namespace) -> None:
    """Merge patch JSON into an existing report file and re-render HTML."""
    report_path = _resolve_under_repo(args.report)
    if not report_path.exists():
        raise SystemExit(f"Report not found: {report_path}")

    if args.patch:
        patch_text = _resolve_under_repo(args.patch).read_text(encoding="utf-8")
    else:
        patch_text = sys.stdin.read()
    if not patch_text.strip():
        raise SystemExit("merge: provide --patch FILE or pipe JSON on stdin")

    base_raw = json.loads(report_path.read_text(encoding="utf-8"))
    if not isinstance(base_raw, dict):
        raise SystemExit("Report root must be a JSON object")
    base = cast(dict[str, Any], base_raw)
    patch_raw = json.loads(patch_text)
    if not isinstance(patch_raw, dict):
        raise SystemExit("Patch root must be a JSON object")
    patch = cast(dict[str, Any], patch_raw)

    _apply_report_patch(base, patch)
    base.pop("_note", None)
    report_path.write_text(
        json.dumps(base, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Report JSON updated: {report_path}")
    html_path = report_path.with_suffix(".html")
    _render_html(json.dumps(base, ensure_ascii=False), html_path)


def cmd_sync(args: argparse.Namespace) -> None:
    """Re-render HTML if missing or older than the JSON file."""
    input_path = _resolve_under_repo(args.report)
    if not input_path.exists():
        raise SystemExit(f"Report not found: {input_path}")

    html_path = (
        _resolve_under_repo(args.output) if args.output else input_path.with_suffix(".html")
    )
    js_mtime = input_path.stat().st_mtime
    need_html = (
        not html_path.exists() or html_path.stat().st_mtime < js_mtime - 0.001
    )
    if need_html:
        cmd_render(argparse.Namespace(input=str(input_path), output=str(html_path) if args.output else None))
        print("sync: rendered (JSON was newer than HTML or HTML missing)")
    else:
        print(f"sync: HTML already up to date ({html_path})")


def _render_html(report_json: str, output_path: Path) -> None:
    """Inject *report_json* into the HTML template and write to *output_path*."""
    template = _TEMPLATE.read_text(encoding="utf-8")
    html = template.replace("__REPORT_JSON__", report_json)
    output_path.write_text(html, encoding="utf-8")
    print(f"Report written to {output_path}")


def cmd_render(args: argparse.Namespace) -> None:
    """Render a single report JSON to HTML."""
    input_path = _resolve_under_repo(args.input)
    data = json.loads(input_path.read_text(encoding="utf-8"))
    output = (
        _resolve_under_repo(args.output) if args.output else input_path.with_suffix(".html")
    )
    _render_html(json.dumps(data, ensure_ascii=False), output)


def cmd_init(args: argparse.Namespace) -> None:
    """Write a new report skeleton JSON and render HTML next to it."""
    scenario_arg = Path(args.scenario)
    scenario_path = (
        scenario_arg.resolve()
        if scenario_arg.is_absolute()
        else (_REPO_ROOT / scenario_arg).resolve()
    )
    if not scenario_path.exists():
        raise SystemExit(f"Scenario file not found: {scenario_path}")

    profile_path = _resolve_profile_path(_REPO_ROOT, args.profile)
    profile_key, llm_model = _load_llm_meta(profile_path)
    title, scenario_id = _scenario_title_and_id(scenario_path)

    project_dir = Path(args.project_dir)
    ts = datetime.now(timezone.utc)
    stamp = ts.strftime("%Y%m%d_%H%M%S")
    iso = ts.strftime("%Y-%m-%dT%H:%M:%SZ")

    if args.out:
        out_json = Path(args.out)
        if not out_json.is_absolute():
            out_json = (_REPO_ROOT / out_json).resolve()
    else:
        out_dir = _REPO_ROOT / "bench" / "reports"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_json = out_dir / f"{scenario_id}_{profile_key}_{stamp}.json"

    data: dict[str, object] = {
        "meta": {
            "scenario_id": scenario_id,
            "scenario_name": title,
            "timestamp": iso,
            "llm_profile": profile_key,
            "llm_model": llm_model,
            "project_dir": str(project_dir),
            "notes": args.notes or "",
        },
        "steps": [],
        "evaluation": {
            "scores": [],
            "average_score": None,
            "pass": None,
            "summary": "",
        },
        "iterations": [],
        "_note": "skeleton — fill steps[] and evaluation, then remove this key",
    }
    out_json.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    try:
        rel_json = out_json.relative_to(_REPO_ROOT)
    except ValueError:
        rel_json = out_json
    print(f"Report JSON written to {out_json}")
    if str(rel_json) != str(out_json):
        print(f"  (from repo root: {rel_json})")
    html_path = out_json.with_suffix(".html")
    _render_html(json.dumps(data, ensure_ascii=False), html_path)
    print(
        "Bench agent: you MUST fill steps[] and evaluation, then re-render HTML.\n"
        "  Option A — merge a patch file or stdin (run from repo root):\n"
        f"    python bench/tools/report.py merge {rel_json} < patch.json\n"
        "  Option B — edit JSON + sync: python bench/tools/report.py sync "
        f"{rel_json}\n"
        "  Stable path next time: report.py init ... -o bench/reports/<name>.json\n"
        "See bench/agent.md",
        file=sys.stderr,
    )


def _validate_report_content(
    data: dict[str, Any],
    *,
    scenario_path: str | None,
) -> list[str]:
    errors: list[str] = []
    meta = data.get("meta")
    if not isinstance(meta, dict):
        errors.append("meta must be an object")

    if isinstance(meta, dict):
        md = cast(dict[str, Any], meta)
        for key in ("scenario_id", "llm_profile"):
            if not isinstance(md.get(key), str) or not str(md.get(key)).strip():
                errors.append(f"meta.{key} must be a non-empty string")

    steps_raw = data.get("steps")
    if not isinstance(steps_raw, list) or len(cast(list[Any], steps_raw)) == 0:
        errors.append("steps must be a non-empty array")

    step_ids: set[str] = set()
    steps_list: list[Any] = cast(list[Any], steps_raw) if isinstance(steps_raw, list) else []
    for i, s in enumerate(steps_list):
        if not isinstance(s, dict):
            errors.append(f"steps[{i}] must be an object")
            continue
        row = cast(dict[str, Any], s)
        sid = row.get("step_id")
        if not isinstance(sid, str) or not sid.strip():
            errors.append(f"steps[{i}].step_id must be a non-empty string")
        else:
            step_ids.add(sid)
        out = row.get("output")
        err = row.get("error")
        has_out = isinstance(out, str) and out.strip() != ""
        has_err = isinstance(err, str) and err.strip() != ""
        if not has_out and not has_err:
            errors.append(
                f"steps[{i}] must include non-empty output or error (partial/failed run)"
            )

    ev = data.get("evaluation")
    if not isinstance(ev, dict):
        errors.append("evaluation must be an object")

    if isinstance(ev, dict):
        ev_d = cast(dict[str, Any], ev)
        scores = ev_d.get("scores")
        if not isinstance(scores, list) or len(cast(list[Any], scores)) == 0:
            errors.append("evaluation.scores must be a non-empty array")

        avg = ev_d.get("average_score")
        if not isinstance(avg, (int, float)):
            errors.append("evaluation.average_score must be a number")

        if ev_d.get("pass") is None:
            errors.append("evaluation.pass must be true or false (not null)")

        if not isinstance(ev_d.get("summary"), str) or not str(ev_d.get("summary")).strip():
            errors.append("evaluation.summary must be a non-empty string")

        if isinstance(scores, list):
            scores_list = cast(list[Any], scores)
            for i, sc in enumerate(scores_list):
                if not isinstance(sc, dict):
                    errors.append(f"evaluation.scores[{i}] must be an object")
                    continue
                sc_d = cast(dict[str, Any], sc)
                for key in ("criterion", "step_id"):
                    if not isinstance(sc_d.get(key), str) or not str(sc_d.get(key)).strip():
                        errors.append(
                            f"evaluation.scores[{i}].{key} must be a non-empty string"
                        )
                sval = sc_d.get("score")
                if not isinstance(sval, (int, float)) or not (1 <= float(sval) <= 5):
                    errors.append(
                        f"evaluation.scores[{i}].score must be a number between 1 and 5"
                    )
                sid_ref = sc_d.get("step_id")
                if isinstance(sid_ref, str) and sid_ref and step_ids and sid_ref not in step_ids:
                    errors.append(
                        f"evaluation.scores[{i}].step_id {sid_ref!r} "
                        "does not match any steps[].step_id"
                    )

    if scenario_path:
        sp = _resolve_under_repo(scenario_path)
        if not sp.exists():
            errors.append(f"Scenario file not found: {sp}")
        elif isinstance(steps_raw, list) and step_ids:
            expected = _scenario_step_ids(sp)
            if expected and set(expected) != step_ids:
                errors.append(
                    "step_id set mismatch: scenario Steps section has "
                    f"{sorted(set(expected))}, report steps have {sorted(step_ids)}"
                )

    return errors


def cmd_validate(args: argparse.Namespace) -> None:
    """Check report JSON shape and optional scenario step_id alignment."""
    report_path = _resolve_under_repo(args.report)
    if not report_path.exists():
        raise SystemExit(f"Report not found: {report_path}")

    raw = json.loads(report_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise SystemExit("Report root must be a JSON object")

    d = cast(dict[str, Any], raw)
    if "_note" in d:
        raise SystemExit(
            "validate: this is an unfilled skeleton (contains '_note' key). "
            "Fill steps[] and evaluation with `report.py merge`, then remove '_note', then validate."
        )

    errors = _validate_report_content(d, scenario_path=args.scenario)
    if errors:
        for e in errors:
            print(e, file=sys.stderr)
        raise SystemExit(1)
    print(f"validate: ok ({report_path})")


def cmd_compare(args: argparse.Namespace) -> None:
    """Render a comparison of multiple report JSONs to HTML."""
    reports: list[dict[str, object]] = []
    for p in args.inputs:
        rp = _resolve_under_repo(p)
        if not rp.exists():
            raise SystemExit(f"Report not found: {rp}")
        reports.append(json.loads(rp.read_text(encoding="utf-8")))
    if len(reports) < 2:
        print("Need at least 2 reports to compare.", file=sys.stderr)
        raise SystemExit(1)

    if args.output:
        output = _resolve_under_repo(args.output)
    else:
        output = _resolve_under_repo(args.inputs[0]).with_name("comparison.html")
    _render_html(json.dumps(reports, ensure_ascii=False), output)


def main() -> None:
    parser = argparse.ArgumentParser(description="Lens benchmark report renderer")
    sub = parser.add_subparsers(dest="command")

    init_p = sub.add_parser(
        "init",
        help="Create report JSON + HTML skeleton (then edit JSON and render again)",
    )
    init_p.add_argument(
        "--scenario",
        required=True,
        help="Path to scenario Markdown (e.g. bench/scenarios/edit_quality.md)",
    )
    init_p.add_argument(
        "--profile",
        required=True,
        help="LLM profile name (bench/llm_profiles/<name>.toml) or path to a TOML file",
    )
    init_p.add_argument(
        "--project-dir",
        required=True,
        help="Benchmark Lens project directory (e.g. bench/projects/lens_bench_…)",
    )
    init_p.add_argument(
        "-o",
        "--out",
        default=None,
        help="Output JSON path (default: bench/reports/<scenario>_<profile>_<UTC stamp>.json)",
    )
    init_p.add_argument(
        "--notes",
        default="",
        help="Optional string stored in meta.notes",
    )

    render_p = sub.add_parser("render", help="Render a single report to HTML")
    render_p.add_argument("input", help="Path to report JSON")
    render_p.add_argument("-o", "--output", help="Output HTML path (default: same name, .html)")

    merge_p = sub.add_parser(
        "merge",
        help="Merge patch JSON into a report (steps, evaluation, meta) and re-render HTML",
    )
    merge_p.add_argument("report", help="Path to report JSON to update")
    merge_p.add_argument(
        "--patch",
        default=None,
        help="Patch JSON file (if omitted, read JSON from stdin)",
    )

    validate_p = sub.add_parser(
        "validate",
        help="Validate report JSON shape (optional: scenario step_id alignment)",
    )
    validate_p.add_argument("report", help="Path to report JSON")
    validate_p.add_argument(
        "--scenario",
        default=None,
        help="Scenario Markdown; if set, ## Steps ids must match report steps",
    )

    sync_p = sub.add_parser(
        "sync",
        help="Re-render HTML if HTML is missing or older than the JSON file",
    )
    sync_p.add_argument("report", help="Path to report JSON")
    sync_p.add_argument("-o", "--output", help="Output HTML path (default: same name, .html)")

    compare_p = sub.add_parser("compare", help="Compare multiple reports side-by-side")
    compare_p.add_argument("inputs", nargs="+", help="Paths to report JSONs")
    compare_p.add_argument("-o", "--output", help="Output HTML path (default: comparison.html)")

    args = parser.parse_args()
    if args.command == "init":
        cmd_init(args)
    elif args.command == "render":
        cmd_render(args)
    elif args.command == "merge":
        cmd_merge(args)
    elif args.command == "validate":
        cmd_validate(args)
    elif args.command == "sync":
        cmd_sync(args)
    elif args.command == "compare":
        cmd_compare(args)
    else:
        parser.print_help()
        raise SystemExit(1)


if __name__ == "__main__":
    main()
