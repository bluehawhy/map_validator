"""Windows CLI for map_validator. Human review is always required."""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import cv2
import yaml

from .road_analysis import RoadSegmenter, analyze_road_mask, draw_review_overlay


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Windows roadview side-road review assistant")
    parser.add_argument("--config", default="config.yaml", help="Settings YAML")
    parser.add_argument("--case-id", required=True, help="Intersection identifier (folder-safe)")
    parser.add_argument("--move", choices=("none", "forward", "backward"), default="none")
    parser.add_argument("--steps", type=int, default=2, help="Number of W/S movements after initial capture")
    parser.add_argument("--open-roadview", action="store_true", help="Click saved button template in the work app")
    parser.add_argument("--no-ai", action="store_true", help="Capture only; skip AI candidate inference")
    return parser.parse_args()


def main() -> int:
    args = arguments()
    if not args.case_id or not all(ch.isalnum() or ch in "-_ " for ch in args.case_id):
        raise ValueError("--case-id supports only letters, numbers, spaces, - and _")
    if args.steps < 0:
        raise ValueError("--steps must be >= 0")
    config_path = Path(args.config).resolve()
    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    from .windows import find_window, click_template_in_window, capture_window, move_roadview

    def based_path(path: str) -> Path:
        p = Path(path)
        return p if p.is_absolute() else config_path.parent / p

    windows_cfg = cfg["windows"]
    if args.open_roadview:
        work = find_window(windows_cfg["work_title"])
        button_path = based_path(windows_cfg["open_button_image"])
        if not click_template_in_window(work, str(button_path)):
            raise RuntimeError("Roadview button image not found. Did not click anything")
        time.sleep(float(cfg.get("capture", {}).get("settle_seconds", 1.5)))

    roadview = find_window(windows_cfg["roadview_title"])
    cap_cfg = cfg.get("capture", {})
    output = based_path(cfg.get("output", {}).get("directory", "results")) / args.case_id
    output.mkdir(parents=True, exist_ok=True)
    ai_cfg = cfg.get("analysis", {})
    segmenter = None if args.no_ai else RoadSegmenter(ai_cfg.get("model_name", "nvidia/segformer-b0-finetuned-ade-512-512"))
    frames = []
    step_count = 0 if args.move == "none" else min(args.steps, int(cfg["movement"].get("max_steps", 5)))
    print("Safety: Mouse to top-left failsafe corner aborts PyAutoGUI operations")
    for idx in range(step_count + 1):
        if idx > 0:
            movement = cfg["movement"]
            key = movement["forward_key"] if args.move == "forward" else movement["backward_key"]
            move_roadview(roadview, key, float(movement.get("hold_seconds", 0.5)))
            time.sleep(float(cap_cfg.get("settle_seconds", 1.5)))
        img = capture_window(roadview, cap_cfg.get("region"))
        base = output / f"frame_{idx:02d}"
        cv2.imwrite(str(base) + ".png", img)
        row = {"frame": idx, "image": base.name + ".png", "left_candidate": None, "right_candidate": None}
        if segmenter is not None:
            mask = segmenter.mask(img)
            vr = tuple(ai_cfg.get("vertical_range", [0.28, 0.60]))
            result = analyze_road_mask(mask, float(ai_cfg.get("side_road_score_threshold", 0.19)), vr)
            overlay = draw_review_overlay(img, mask, result, vr)
            cv2.imwrite(str(base) + "_overlay.png", overlay)
            row.update(result.as_dict())
            row["overlay"] = base.name + "_overlay.png"
        frames.append(row)
        print(f"Captured {idx+1}/{step_count+1}: {base}.png")

    def candidate_summary(key: str) -> str:
        if segmenter is None:
            return "not_analyzed"
        return "possible" if any(bool(x[key]) for x in frames) else "not_detected_review_required"

    report = {
        "case_id": args.case_id,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "movement": args.move,
        "frames": frames,
        "left_road": candidate_summary("left_candidate"),
        "right_road": candidate_summary("right_candidate"),
        "final_decision": "requires_human_review",
        "warning": "Segmentation ROI is a candidate detector, not proof of a turnable side road.",
    }
    (output / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("case_id", "left_road", "right_road", "final_decision")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
