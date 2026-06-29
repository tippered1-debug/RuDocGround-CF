from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


def _safe_div(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def _load_report(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_font(size: int = 16) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Unicode.ttf", size=size)
    except Exception:
        return ImageFont.load_default()


def _wrap_label(text: str, limit: int = 16) -> str:
    if len(text) <= limit:
        return text
    parts = text.replace("_", " ").split()
    lines: list[str] = []
    current = ""
    for part in parts:
        candidate = f"{current} {part}".strip()
        if current and len(candidate) > limit:
            lines.append(current)
            current = part
        else:
            current = candidate
    if current:
        lines.append(current)
    return "\n".join(lines[:3])


def _case_ids_from_records(report: dict[str, Any]) -> list[str]:
    records = report.get("records", [])
    case_ids = sorted({row["key"]["case_id"] for row in records})
    if case_ids:
        return case_ids
    by_case = report.get("by_case_id", [])
    if by_case and "case_id" in by_case[0]:
        return [row["case_id"] for row in by_case]
    return []


def _aggregate_by_case(report: dict[str, Any]) -> list[dict[str, Any]]:
    if report.get("by_case_id"):
        return report["by_case_id"]
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in report.get("records", []):
        grouped[str(row["key"]["case_id"])].append(row)
    results = []
    for case_id, items in sorted(grouped.items()):
        decision_records = [row for row in items if row.get("decision_required")]
        results.append(
            {
                "case_id": case_id,
                "count": len(items),
                "answer_accuracy": _safe_div(sum(1 for row in items if row["answer_correct"]), len(items)),
                "decision_accuracy": _safe_div(sum(1 for row in decision_records if row["decision_correct"]), len(decision_records)),
                "decision_required_count": len(decision_records),
                "evidence_precision": _safe_div(sum(row["evidence_precision"] for row in items), len(items)),
                "evidence_recall": _safe_div(sum(row["evidence_recall"] for row in items), len(items)),
                "evidence_f1": _safe_div(sum(row["evidence_f1"] for row in items), len(items)),
                "missing_information_accuracy": _safe_div(sum(1 for row in items if row["missing_information_correct"]), len(items)),
                "unsupported_evidence_rate": _safe_div(sum(row["unsupported_evidence_rate"] for row in items), len(items)),
            }
        )
    return results


def _aggregate_by_skill(report: dict[str, Any]) -> list[dict[str, Any]]:
    if report.get("by_skill"):
        return report["by_skill"]
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in report.get("records", []):
        grouped[str(row.get("skill", "unknown"))].append(row)
    results = []
    for skill, items in sorted(grouped.items()):
        decision_records = [row for row in items if row.get("decision_required")]
        results.append(
            {
                "skill": skill,
                "count": len(items),
                "answer_accuracy": _safe_div(sum(1 for row in items if row["answer_correct"]), len(items)),
                "decision_accuracy": _safe_div(sum(1 for row in decision_records if row["decision_correct"]), len(decision_records)),
                "decision_required_count": len(decision_records),
                "evidence_precision": _safe_div(sum(row["evidence_precision"] for row in items), len(items)),
                "evidence_recall": _safe_div(sum(row["evidence_recall"] for row in items), len(items)),
                "evidence_f1": _safe_div(sum(row["evidence_f1"] for row in items), len(items)),
                "missing_information_accuracy": _safe_div(sum(1 for row in items if row["missing_information_correct"]), len(items)),
                "unsupported_evidence_rate": _safe_div(sum(row["unsupported_evidence_rate"] for row in items), len(items)),
            }
        )
    return results


def _aggregate_by_answer_type(report: dict[str, Any]) -> list[dict[str, Any]]:
    if report.get("by_answer_type"):
        return report["by_answer_type"]
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in report.get("records", []):
        grouped[str(row["answer_type"])].append(row)
    results = []
    for answer_type, items in sorted(grouped.items()):
        decision_records = [row for row in items if row.get("decision_required")]
        results.append(
            {
                "answer_type": answer_type,
                "count": len(items),
                "answer_accuracy": _safe_div(sum(1 for row in items if row["answer_correct"]), len(items)),
                "decision_accuracy": _safe_div(sum(1 for row in decision_records if row["decision_correct"]), len(decision_records)),
                "decision_required_count": len(decision_records),
                "evidence_precision": _safe_div(sum(row["evidence_precision"] for row in items), len(items)),
                "evidence_recall": _safe_div(sum(row["evidence_recall"] for row in items), len(items)),
                "evidence_f1": _safe_div(sum(row["evidence_f1"] for row in items), len(items)),
                "missing_information_accuracy": _safe_div(sum(1 for row in items if row["missing_information_correct"]), len(items)),
                "unsupported_evidence_rate": _safe_div(sum(row["unsupported_evidence_rate"] for row in items), len(items)),
            }
        )
    return results


def _counterfactual_by_case(report: dict[str, Any]) -> list[dict[str, Any]]:
    if report.get("counterfactual_by_case"):
        return report["counterfactual_by_case"]
    rows = report.get("counterfactual", {}).get("rows", [])
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["case_id"])].append(row)
    results = []
    for case_id, items in sorted(grouped.items()):
        flip_items = [row for row in items if row.get("expected_change")]
        invariance_items = [row for row in items if not row.get("expected_change")]
        results.append(
            {
                "case_id": case_id,
                "flip_score": _safe_div(sum(row["score"] for row in flip_items), len(flip_items)),
                "flip_count": len(flip_items),
                "invariance_score": _safe_div(sum(row["score"] for row in invariance_items), len(invariance_items)),
                "invariance_count": len(invariance_items),
            }
        )
    return results


def _errors(report: dict[str, Any]) -> list[dict[str, Any]]:
    errors = list(report.get("errors", []))
    if errors:
        return errors
    errors = []
    for issue in report.get("issues", []):
        errors.append({"kind": issue.get("kind", "issue"), "message": issue.get("message", ""), "lineno": issue.get("lineno")})
    return errors


def _make_canvas(width: int, height: int, title: str) -> tuple[Image.Image, ImageDraw.ImageDraw, ImageFont.ImageFont, ImageFont.ImageFont]:
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    title_font = _load_font(26)
    body_font = _load_font(15)
    draw.text((24, 18), title, fill="black", font=title_font)
    return img, draw, title_font, body_font


def _write_svg(path: Path, width: int, height: int, title: str, body: str) -> None:
    path.write_text(
        f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <rect width="100%" height="100%" fill="white"/>
  <text x="24" y="38" font-size="26" font-family="Arial, sans-serif" fill="black">{title}</text>
  {body}
</svg>
""",
        encoding="utf-8",
    )


def _save_png_svg(base_path: Path, img: Image.Image, svg_body: str, title: str) -> None:
    png_path = base_path.with_suffix(".png")
    svg_path = base_path.with_suffix(".svg")
    img.save(png_path)
    _write_svg(svg_path, img.width, img.height, title, svg_body)


def _draw_hbar_chart(items: list[tuple[str, float]], title: str, base_path: Path, *, mode_label: str = "") -> None:
    width, height = 1200, max(320, 80 + 44 * len(items))
    img, draw, _, font = _make_canvas(width, height, f"{mode_label} {title}".strip())
    left = 340
    top = 70
    chart_w = width - left - 80
    bar_h = 24
    gap = 18
    max_value = max([value for _, value in items] or [1.0]) or 1.0
    svg_parts = []
    for idx, (label, value) in enumerate(items):
        y = top + idx * (bar_h + gap)
        bar_w = int(chart_w * (value / max_value))
        draw.text((24, y - 2), _wrap_label(label), fill="black", font=font)
        draw.rectangle([left, y, left + bar_w, y + bar_h], fill="#1f77b4")
        draw.text((left + bar_w + 8, y - 2), f"{value:.2f}", fill="black", font=font)
        svg_parts.append(
            f'<text x="24" y="{y + 18}" font-size="15" font-family="Arial, sans-serif">{_wrap_label(label).replace(chr(10), " | ")}</text>'
        )
        svg_parts.append(
            f'<rect x="{left}" y="{y}" width="{bar_w}" height="{bar_h}" fill="#1f77b4" />'
        )
        svg_parts.append(
            f'<text x="{left + bar_w + 8}" y="{y + 18}" font-size="15" font-family="Arial, sans-serif">{value:.2f}</text>'
        )
    _save_png_svg(base_path, img, "\n  ".join(svg_parts), f"{mode_label} {title}".strip())


def _draw_grouped_chart(labels: list[str], series: list[tuple[str, list[float]]], title: str, base_path: Path, *, mode_label: str = "") -> None:
    width = max(1100, 80 * len(labels) + 220)
    height = 540
    img, draw, _, font = _make_canvas(width, height, f"{mode_label} {title}".strip())
    left = 80
    top = 90
    bottom = 120
    chart_h = height - top - bottom
    chart_w = width - left - 60
    max_value = max([value for _, values in series for value in values] or [1.0]) or 1.0
    group_w = chart_w / max(1, len(labels))
    bar_gap = 6
    series_count = max(1, len(series))
    bar_w = max(8, int((group_w - 20) / series_count) - bar_gap)
    colors = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728"]
    svg_parts = []
    for x_idx, label in enumerate(labels):
        group_x = left + x_idx * group_w
        draw.multiline_text((group_x + 2, height - 92), _wrap_label(label, 12), fill="black", font=font, anchor="la", align="center")
        svg_parts.append(f'<text x="{group_x + group_w/2:.1f}" y="{height - 80}" font-size="14" font-family="Arial, sans-serif" text-anchor="middle">{_wrap_label(label, 12).replace(chr(10), "&#10;")}</text>')
        for s_idx, (series_name, values) in enumerate(series):
            value = values[x_idx] if x_idx < len(values) else 0.0
            bar_h = int(chart_h * (value / max_value))
            x = group_x + 10 + s_idx * (bar_w + bar_gap)
            y = top + (chart_h - bar_h)
            color = colors[s_idx % len(colors)]
            draw.rectangle([x, y, x + bar_w, top + chart_h], fill=color)
            draw.text((x, y - 20), f"{value:.2f}", fill="black", font=font)
            svg_parts.append(f'<rect x="{x}" y="{y}" width="{bar_w}" height="{bar_h}" fill="{color}" />')
            svg_parts.append(f'<text x="{x}" y="{y - 4}" font-size="14" font-family="Arial, sans-serif">{value:.2f}</text>')
    legend_x = width - 250
    legend_y = 60
    for idx, (series_name, _) in enumerate(series):
        color = colors[idx % len(colors)]
        y = legend_y + idx * 22
        draw.rectangle([legend_x, y, legend_x + 14, y + 14], fill=color)
        draw.text((legend_x + 22, y - 2), series_name, fill="black", font=font)
        svg_parts.append(f'<rect x="{legend_x}" y="{y}" width="14" height="14" fill="{color}" />')
        svg_parts.append(f'<text x="{legend_x + 22}" y="{y + 12}" font-size="14" font-family="Arial, sans-serif">{series_name}</text>')
    _save_png_svg(base_path, img, "\n  ".join(svg_parts), f"{mode_label} {title}".strip())


def _draw_overall_metrics(report: dict[str, Any], output_dir: Path, mode_label: str) -> None:
    metrics = report["overall"]
    items = [
        ("Answer accuracy", metrics["answer_accuracy"]),
        ("Decision accuracy", metrics["decision_accuracy"]),
        ("Evidence F1", metrics["evidence_f1"]),
        ("Missing-info accuracy", metrics["missing_information_accuracy"]),
        ("Unsupported evidence rate", metrics["unsupported_evidence_rate"]),
    ]
    _draw_hbar_chart(items, "Overall Metrics", output_dir / "overall_metrics", mode_label=mode_label)


def _draw_answer_accuracy_by_case(report: dict[str, Any], output_dir: Path, mode_label: str) -> None:
    rows = _aggregate_by_case(report)
    items = [(row["case_id"], row["answer_accuracy"]) for row in rows]
    _draw_hbar_chart(items, "Answer Accuracy by Case", output_dir / "answer_accuracy_by_case", mode_label=mode_label)


def _draw_flip_invariance_by_case(report: dict[str, Any], output_dir: Path, mode_label: str) -> None:
    rows = _counterfactual_by_case(report)
    labels = [row["case_id"] for row in rows]
    series = [
        ("Flip score", [row["flip_score"] for row in rows]),
        ("Invariance score", [row["invariance_score"] for row in rows]),
    ]
    _draw_grouped_chart(labels, series, "Flip / Invariance by Case", output_dir / "flip_invariance_by_case", mode_label=mode_label)


def _draw_accuracy_by_skill(report: dict[str, Any], output_dir: Path, mode_label: str) -> None:
    rows = _aggregate_by_skill(report)
    items = [(row["skill"], row["answer_accuracy"]) for row in rows]
    _draw_hbar_chart(items, "Answer Accuracy by Skill", output_dir / "accuracy_by_skill", mode_label=mode_label)


def _draw_evidence_metrics_by_case(report: dict[str, Any], output_dir: Path, mode_label: str) -> None:
    rows = _aggregate_by_case(report)
    labels = [row["case_id"] for row in rows]
    series = [
        ("Precision", [row["evidence_precision"] for row in rows]),
        ("Recall", [row["evidence_recall"] for row in rows]),
        ("F1", [row["evidence_f1"] for row in rows]),
    ]
    _draw_grouped_chart(labels, series, "Evidence Metrics by Case", output_dir / "evidence_metrics_by_case", mode_label=mode_label)


def _draw_error_categories(report: dict[str, Any], output_dir: Path, mode_label: str) -> None:
    errors = report.get("errors", [])
    grouped: dict[str, int] = defaultdict(int)
    for row in errors:
        grouped[str(row.get("kind", "unknown"))] += 1
    items = sorted(grouped.items())
    if not items:
        items = [("no_errors", 0.0)]
    _draw_hbar_chart([(kind, float(count)) for kind, count in items], "Error Categories", output_dir / "error_categories", mode_label=mode_label)


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build RuDocGround-CF figures from a report JSON")
    parser.add_argument("--report", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    report = _load_report(Path(args.report))
    case_count = len(_case_ids_from_records(report))
    mode_label = "Pilot / single-case" if case_count <= 1 else "Benchmark"
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    _draw_overall_metrics(report, output_dir, mode_label)
    _draw_answer_accuracy_by_case(report, output_dir, mode_label)
    _draw_flip_invariance_by_case(report, output_dir, mode_label)
    _draw_accuracy_by_skill(report, output_dir, mode_label)
    _draw_evidence_metrics_by_case(report, output_dir, mode_label)
    _draw_error_categories(report, output_dir, mode_label)

    print(json.dumps({"output_dir": str(output_dir), "figure_set": ["overall_metrics", "answer_accuracy_by_case", "flip_invariance_by_case", "accuracy_by_skill", "evidence_metrics_by_case", "error_categories"], "mode_label": mode_label}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
