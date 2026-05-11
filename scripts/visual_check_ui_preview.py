from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageStat

from capture_ui_preview import CRITICAL_VIEWS, normalize_views, run_capture


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Light visual checks for CineSort preview UI.")
    parser.add_argument(
        "--dev", action="store_true", help="Authorize dev-only preview tooling. Alternative: DEV_MODE=1"
    )
    parser.add_argument("--refresh-baseline", action="store_true", help="Regenerate the baseline screenshots and exit.")
    parser.add_argument(
        "--baseline-dir", default="", help="Baseline directory. Default: tests/ui_preview_baselines/critical"
    )
    parser.add_argument(
        "--report-dir", default="", help="Report directory. Default: build/ui_preview_visual_check/latest"
    )
    parser.add_argument("--scenario", default="run_recent_safe", help="Scenario id when not using recommended mapping.")
    parser.add_argument(
        "--recommended", dest="recommended", action="store_true", help="Use the recommended scenario per view."
    )
    parser.add_argument(
        "--no-recommended", dest="recommended", action="store_false", help="Use a single scenario for all views."
    )
    parser.set_defaults(recommended=True)
    parser.add_argument("--views", default=",".join(CRITICAL_VIEWS), help="Comma-separated views to check.")
    parser.add_argument("--width", default=1600, type=int, help="Viewport width for captures.")
    parser.add_argument("--height", default=1100, type=int, help="Viewport height for captures.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host for the local preview server.")
    parser.add_argument("--port", default=0, type=int, help="Bind port. Use 0 for an ephemeral port.")
    parser.add_argument("--max-diff-ratio", default=0.0025, type=float, help="Max changed-pixel ratio before failure.")
    parser.add_argument("--max-mean-diff", default=1.0, type=float, help="Max grayscale mean diff before failure.")
    return parser.parse_args()


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def default_baseline_dir() -> Path:
    return repo_root() / "tests" / "ui_preview_baselines" / "critical"


def default_report_dir() -> Path:
    return repo_root() / "build" / "ui_preview_visual_check" / "latest"


def ensure_clean_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def capture_namespace(args: argparse.Namespace, output_dir: Path, views: list[str]) -> argparse.Namespace:
    return argparse.Namespace(
        dev=bool(getattr(args, "dev", False)),
        host=args.host,
        port=args.port,
        scenario=args.scenario,
        recommended=args.recommended,
        views=",".join(views),
        width=args.width,
        height=args.height,
        output_dir=str(output_dir),
    )


def load_manifest(directory: Path) -> dict[str, dict[str, str]]:
    manifest_path = directory / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing manifest: {manifest_path}")
    entries = json.loads(manifest_path.read_text(encoding="utf-8"))
    mapping: dict[str, dict[str, str]] = {}
    for entry in entries:
        view = str(entry.get("view") or "").strip().lower()
        file_name = str(entry.get("file") or "").strip()
        if not view or not file_name:
            continue
        mapping[view] = {
            "file": file_name,
            "label": str(entry.get("label") or view),
            "scenario": str(entry.get("scenario") or ""),
        }
    return mapping


def pad_to_common_size(left: Image.Image, right: Image.Image) -> tuple[Image.Image, Image.Image, bool]:
    size_mismatch = left.size != right.size
    if not size_mismatch:
        return left.convert("RGBA"), right.convert("RGBA"), False
    max_width = max(left.size[0], right.size[0])
    max_height = max(left.size[1], right.size[1])

    def pad(image: Image.Image) -> Image.Image:
        canvas = Image.new("RGBA", (max_width, max_height), (11, 18, 29, 255))
        canvas.paste(image.convert("RGBA"), (0, 0))
        return canvas

    return pad(left), pad(right), True


def changed_pixel_ratio(mask: Image.Image) -> float:
    histogram = mask.histogram()
    changed = int(sum(histogram[1:]))
    total = int(mask.size[0] * mask.size[1]) or 1
    return changed / total


def save_diff_image(baseline: Image.Image, current: Image.Image, diff_mask: Image.Image, target: Path) -> None:
    highlight = Image.new("RGBA", current.size, (229, 57, 53, 0))
    highlight.putalpha(diff_mask.point(lambda value: 160 if value else 0))
    overlay = Image.alpha_composite(current, highlight)

    panel_gap = 16
    panel_width = baseline.size[0]
    panel_height = baseline.size[1]
    canvas = Image.new("RGBA", (panel_width * 3 + panel_gap * 4, panel_height + panel_gap * 2), (12, 18, 28, 255))
    canvas.paste(baseline, (panel_gap, panel_gap))
    canvas.paste(current, (panel_gap * 2 + panel_width, panel_gap))
    canvas.paste(overlay, (panel_gap * 3 + panel_width * 2, panel_gap))
    target.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(target)


def compare_view(
    view: str,
    baseline_file: Path,
    current_file: Path,
    diff_file: Path,
    max_diff_ratio: float,
    max_mean_diff: float,
) -> dict[str, object]:
    baseline_img = Image.open(baseline_file)
    current_img = Image.open(current_file)
    baseline_pad, current_pad, size_mismatch = pad_to_common_size(baseline_img, current_img)
    diff = ImageChops.difference(baseline_pad, current_pad)
    diff_gray = diff.convert("L")
    mask = diff_gray.point(lambda value: 255 if value else 0)
    ratio = changed_pixel_ratio(mask)
    mean_diff = float(ImageStat.Stat(diff_gray).mean[0])
    has_diff = diff.getbbox() is not None
    save_diff_image(baseline_pad, current_pad, mask, diff_file)
    passed = (not size_mismatch) and ratio <= max_diff_ratio and mean_diff <= max_mean_diff
    return {
        "view": view,
        "baseline_file": str(baseline_file),
        "current_file": str(current_file),
        "diff_file": str(diff_file),
        "size_mismatch": size_mismatch,
        "has_diff": has_diff,
        "diff_ratio": ratio,
        "mean_diff": mean_diff,
        "passed": passed,
    }


def relpath(path: Path, base: Path) -> str:
    return os.path.relpath(path, base).replace("\\", "/")


def write_html_report(report_dir: Path, results: list[dict[str, object]]) -> Path:
    fail_count = sum(1 for item in results if not item["passed"])
    rows = []
    for item in results:
        status = "PASS" if item["passed"] else "FAIL"
        row_cls = "pass" if item["passed"] else "fail"
        baseline_cell = "<span>—</span>"
        current_cell = "<span>—</span>"
        diff_cell = "<span>—</span>"
        if item.get("baseline_file"):
            baseline_cell = '<img src="{src}" alt="baseline {view}">'.format(
                src=relpath(Path(str(item["baseline_file"])), report_dir),
                view=item["view"],
            )
        if item.get("current_file"):
            current_cell = '<img src="{src}" alt="current {view}">'.format(
                src=relpath(Path(str(item["current_file"])), report_dir),
                view=item["view"],
            )
        if item.get("diff_file"):
            diff_cell = '<img src="{src}" alt="diff {view}">'.format(
                src=relpath(Path(str(item["diff_file"])), report_dir),
                view=item["view"],
            )
        rows.append(
            '<tr class="{row_cls}">'
            "<td><strong>{view}</strong><div>{status}</div></td>"
            "<td>{ratio:.4%}</td>"
            "<td>{mean:.2f}</td>"
            "<td>{size}</td>"
            "<td>{baseline}</td>"
            "<td>{current}</td>"
            "<td>{diff}</td>"
            "</tr>".format(
                row_cls=row_cls,
                view=item["view"],
                status=status,
                ratio=float(item["diff_ratio"]),
                mean=float(item["mean_diff"]),
                size="oui" if item["size_mismatch"] else "non",
                baseline=baseline_cell,
                current=current_cell,
                diff=diff_cell,
            )
        )
    html = """<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8" />
  <title>CineSort UI Visual Check</title>
  <style>
    body {{ font-family: Segoe UI, Arial, sans-serif; margin: 24px; background: #0f1720; color: #e5edf5; }}
    h1, h2 {{ margin: 0 0 12px; }}
    p {{ margin: 0 0 16px; color: #b9c7d8; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ border: 1px solid rgba(255,255,255,0.12); padding: 10px; vertical-align: top; }}
    th {{ background: rgba(255,255,255,0.06); text-align: left; }}
    tr.pass td:first-child {{ border-left: 4px solid #2e7d32; }}
    tr.fail td:first-child {{ border-left: 4px solid #e53935; }}
    img {{ width: 320px; display: block; border: 1px solid rgba(255,255,255,0.1); background: #111827; }}
    code {{ background: rgba(255,255,255,0.08); padding: 2px 6px; border-radius: 6px; }}
  </style>
</head>
<body>
  <h1>CineSort UI Visual Check</h1>
  <p>{fail_count} régression(s) détectée(s) sur {total} vue(s).</p>
  <table>
    <thead>
      <tr>
        <th>Vue</th>
        <th>Pixels changés</th>
        <th>Diff moyenne</th>
        <th>Taille différente</th>
        <th>Baseline</th>
        <th>Courant</th>
        <th>Diff</th>
      </tr>
    </thead>
    <tbody>
      {rows}
    </tbody>
  </table>
</body>
</html>
""".format(fail_count=fail_count, total=len(results), rows="\n".join(rows))
    path = report_dir / "report.html"
    path.write_text(html, encoding="utf-8")
    return path


def write_json_report(report_dir: Path, results: list[dict[str, object]], args: argparse.Namespace) -> Path:
    path = report_dir / "report.json"
    payload = {
        "recommended": bool(args.recommended),
        "scenario": str(args.scenario),
        "views": [str(item["view"]) for item in results],
        "thresholds": {
            "max_diff_ratio": float(args.max_diff_ratio),
            "max_mean_diff": float(args.max_mean_diff),
        },
        "summary": {
            "total": len(results),
            "failed": sum(1 for item in results if not item["passed"]),
        },
        "results": results,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def refresh_baseline(args: argparse.Namespace, baseline_dir: Path, views: list[str]) -> None:
    ensure_clean_dir(baseline_dir)
    run_capture(capture_namespace(args, baseline_dir, views))


def missing_result(view: str, reason: str) -> dict[str, object]:
    return {
        "view": view,
        "passed": False,
        "reason": reason,
        "baseline_file": "",
        "current_file": "",
        "diff_file": "",
        "size_mismatch": False,
        "has_diff": False,
        "diff_ratio": 1.0,
        "mean_diff": 255.0,
    }


def compare_against_baseline(
    args: argparse.Namespace, baseline_dir: Path, report_dir: Path, views: list[str]
) -> list[dict[str, object]]:
    if not baseline_dir.exists():
        raise SystemExit(f"Baseline directory does not exist: {baseline_dir}\nRun with --refresh-baseline first.")
    baseline_manifest = load_manifest(baseline_dir)
    current_dir = report_dir / "current"
    diff_dir = report_dir / "diff"
    ensure_clean_dir(report_dir)
    current_dir.mkdir(parents=True, exist_ok=True)
    diff_dir.mkdir(parents=True, exist_ok=True)
    run_capture(capture_namespace(args, current_dir, views))
    current_manifest = load_manifest(current_dir)

    results: list[dict[str, object]] = []
    for view in views:
        if view not in baseline_manifest:
            results.append(missing_result(view, "missing_baseline"))
            continue
        if view not in current_manifest:
            results.append(missing_result(view, "missing_current"))
            continue
        baseline_file = baseline_dir / baseline_manifest[view]["file"]
        current_file = current_dir / current_manifest[view]["file"]
        if not baseline_file.exists():
            results.append(missing_result(view, "missing_baseline_file"))
            continue
        if not current_file.exists():
            results.append(missing_result(view, "missing_current_file"))
            continue
        diff_file = diff_dir / current_manifest[view]["file"].replace(".png", "__diff.png")
        results.append(
            compare_view(
                view=view,
                baseline_file=baseline_file,
                current_file=current_file,
                diff_file=diff_file,
                max_diff_ratio=float(args.max_diff_ratio),
                max_mean_diff=float(args.max_mean_diff),
            )
        )
    write_json_report(report_dir, results, args)
    write_html_report(report_dir, results)
    return results


def main() -> int:
    args = parse_args()
    views = normalize_views(args.views)
    baseline_dir = Path(args.baseline_dir) if args.baseline_dir else default_baseline_dir()
    report_dir = Path(args.report_dir) if args.report_dir else default_report_dir()

    if args.refresh_baseline:
        refresh_baseline(args, baseline_dir, views)
        print(f"Baseline refreshed: {baseline_dir}")
        return 0

    results = compare_against_baseline(args, baseline_dir, report_dir, views)
    fail_count = sum(1 for item in results if not item["passed"])
    print(f"Visual check completed: {len(results)} views, {fail_count} failure(s).")
    print(report_dir / "report.html")
    print(report_dir / "report.json")
    return 1 if fail_count else 0


if __name__ == "__main__":
    sys.exit(main())
