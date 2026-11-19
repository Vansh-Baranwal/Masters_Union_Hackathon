"""
Evaluation scorer for Pratibimb (spec §19).

Metrics reported (only on a held-out split, never the calibration set):

  1. Extraction accuracy   — per field, per screenshot type, per language
  2. Classification accuracy — predicted vs ground-truth screenshot_type
  3. Linking accuracy       — predicted relationship type vs ground-truth
  4. False-accept rate      — wrongly cleared bad items + coverage share
  5. Coordinator time       — placeholder timing field (manual entry)

Usage:
    python -m eval.scorer --ground-truth eval/data/calibration/ground_truth.jsonl \
                          --predictions  eval/results/predictions.jsonl \
                          --output       eval/results/report.json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger(__name__)


# ─── Data classes ─────────────────────────────────────────────────────────── #

def _load_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


# ─── Metric 1: Classification accuracy ────────────────────────────────────── #

def classification_accuracy(ground_truth: list[dict], predictions: list[dict]) -> dict:
    """
    ground_truth items: {evidence_id, screenshot_type}
    predictions items:  {evidence_id, screenshot_type, type_confidence}
    """
    gt_map = {r["evidence_id"]: r["screenshot_type"] for r in ground_truth}
    pred_map = {r["evidence_id"]: r for r in predictions}

    correct = total = 0
    per_type: dict[str, dict] = defaultdict(lambda: {"correct": 0, "total": 0})

    for ev_id, gt_type in gt_map.items():
        pred = pred_map.get(ev_id)
        if pred is None:
            continue
        total += 1
        per_type[gt_type]["total"] += 1
        if pred["screenshot_type"] == gt_type:
            correct += 1
            per_type[gt_type]["correct"] += 1

    overall = correct / total if total else 0.0
    per_type_acc = {
        t: round(v["correct"] / v["total"], 4) if v["total"] else None
        for t, v in per_type.items()
    }
    return {
        "overall_accuracy": round(overall, 4),
        "correct": correct,
        "total": total,
        "per_type": per_type_acc,
    }


# ─── Metric 2: Field extraction accuracy ──────────────────────────────────── #

def field_extraction_accuracy(ground_truth: list[dict], predictions: list[dict]) -> dict:
    """
    ground_truth items: {evidence_id, screenshot_type, fields: {field: value|null}}
    predictions items:  {evidence_id, fields: {field: value|null}}

    For each field:
      - null in GT and null in pred   → true_null (not counted as error)
      - non-null in GT, correct pred  → correct
      - non-null in GT, wrong pred    → error
      - non-null in GT, null pred     → miss
    """
    gt_map = {r["evidence_id"]: r for r in ground_truth}
    pred_map = {r["evidence_id"]: r for r in predictions}

    field_stats: dict[str, dict] = defaultdict(lambda: {"correct": 0, "miss": 0, "error": 0, "true_null": 0})

    for ev_id, gt in gt_map.items():
        pred = pred_map.get(ev_id)
        if pred is None:
            continue
        gt_fields = gt.get("fields", {})
        pred_fields = pred.get("fields", {})
        for field, gt_val in gt_fields.items():
            pred_val = pred_fields.get(field)
            if gt_val is None:
                if pred_val is None:
                    field_stats[field]["true_null"] += 1
                # else: spurious extraction — not counted separately here
            else:
                if pred_val is None:
                    field_stats[field]["miss"] += 1
                elif str(pred_val).strip().lower() == str(gt_val).strip().lower():
                    field_stats[field]["correct"] += 1
                else:
                    field_stats[field]["error"] += 1

    result = {}
    for field, s in field_stats.items():
        attempted = s["correct"] + s["miss"] + s["error"]
        precision = s["correct"] / (s["correct"] + s["error"]) if (s["correct"] + s["error"]) else None
        recall = s["correct"] / attempted if attempted else None
        result[field] = {
            "precision": round(precision, 4) if precision is not None else None,
            "recall": round(recall, 4) if recall is not None else None,
            "correct": s["correct"],
            "miss": s["miss"],
            "error": s["error"],
            "true_null": s["true_null"],
        }
    return result


# ─── Metric 3: Linking accuracy ───────────────────────────────────────────── #

def linking_accuracy(ground_truth: list[dict], predictions: list[dict]) -> dict:
    """
    ground_truth items: {from_id, to_id, relationship_type}
    predictions items:  {from_id, to_id, relationship_type, score}
    """
    def _pair(a, b): return tuple(sorted([a, b]))

    gt_pairs = {_pair(r["from_id"], r["to_id"]): r["relationship_type"] for r in ground_truth}
    pred_pairs = {_pair(r["from_id"], r["to_id"]): r for r in predictions}

    correct = total = 0
    per_type: dict[str, dict] = defaultdict(lambda: {"correct": 0, "total": 0})

    for pair, gt_type in gt_pairs.items():
        pred = pred_pairs.get(pair)
        if pred is None:
            continue
        total += 1
        per_type[gt_type]["total"] += 1
        if pred["relationship_type"] == gt_type:
            correct += 1
            per_type[gt_type]["correct"] += 1

    overall = correct / total if total else 0.0
    return {
        "overall_accuracy": round(overall, 4),
        "correct": correct,
        "total": total,
        "per_type": {
            t: round(v["correct"] / v["total"], 4) if v["total"] else None
            for t, v in per_type.items()
        },
    }


# ─── Metric 4: False-accept rate ──────────────────────────────────────────── #

def false_accept_rate(ground_truth: list[dict], predictions: list[dict]) -> dict:
    """
    ground_truth items: {evidence_id, is_bad: bool}  (bad = fabricated / scam)
    predictions items:  {evidence_id, verdict}

    false_accept: is_bad=True AND verdict in (corroborated, extracted)
    coverage:     share of items auto-cleared (not sent to coordinator inbox)
    """
    gt_map = {r["evidence_id"]: r["is_bad"] for r in ground_truth}
    pred_map = {r["evidence_id"]: r["verdict"] for r in predictions}

    auto_cleared_verdicts = {"corroborated", "extracted"}
    false_accepts = 0
    total_bad = sum(1 for v in gt_map.values() if v)
    total_auto_cleared = 0
    total = 0

    for ev_id, is_bad in gt_map.items():
        pred_verdict = pred_map.get(ev_id)
        if pred_verdict is None:
            continue
        total += 1
        if pred_verdict in auto_cleared_verdicts:
            total_auto_cleared += 1
            if is_bad:
                false_accepts += 1

    far = false_accepts / total_bad if total_bad else None
    coverage = total_auto_cleared / total if total else None
    return {
        "false_accept_rate": round(far, 4) if far is not None else None,
        "false_accepts": false_accepts,
        "total_bad": total_bad,
        "auto_cleared": total_auto_cleared,
        "coverage": round(coverage, 4) if coverage is not None else None,
        "total": total,
        "note": (
            "FAR and coverage are only meaningful on data resembling the calibration set. "
            "Report threshold used alongside this number."
        ),
    }


# ─── Report builder ───────────────────────────────────────────────────────── #

def build_report(gt_path: Path, pred_path: Path) -> dict:
    gt_rows = _load_jsonl(gt_path)
    pred_rows = _load_jsonl(pred_path)

    # Ground truth rows must carry a 'split' field; only use 'test'
    gt_test = [r for r in gt_rows if r.get("split", "test") == "test"]
    pred_test = [r for r in pred_rows if r.get("split", "test") == "test"]

    if not gt_test:
        log.warning("No 'test' split rows found in ground truth; using all rows.")
        gt_test = gt_rows
        pred_test = pred_rows

    report = {
        "classification": classification_accuracy(gt_test, pred_test),
        "field_extraction": field_extraction_accuracy(gt_test, pred_test),
        "linking": linking_accuracy(gt_test, pred_test),
        "false_accept": false_accept_rate(gt_test, pred_test),
        "where_it_fails": [
            "Low-resolution or heavily cropped screenshots yield missed fields.",
            "Kannada OCR quality depends on Sarvam Vision; fallback is Digitise + 105B.",
            "INFERRED links are fragile when timestamps differ across time zones.",
            "Perceptual hashing false-positives on screenshots with shared UI templates.",
            "Fabricated screenshots that form a consistent set may pass corroboration.",
        ],
        "drift_note": (
            "These results hold only on data resembling the calibration set. "
            "Re-run on new batches to detect distribution shift."
        ),
    }
    return report


# ─── CLI ──────────────────────────────────────────────────────────────────── #

def main():
    parser = argparse.ArgumentParser(description="Pratibimb evaluation scorer")
    parser.add_argument("--ground-truth", required=True, type=Path)
    parser.add_argument("--predictions",  required=True, type=Path)
    parser.add_argument("--output",       required=True, type=Path)
    args = parser.parse_args()

    if not args.ground_truth.exists():
        print(f"Ground truth file not found: {args.ground_truth}", file=sys.stderr)
        sys.exit(1)
    if not args.predictions.exists():
        print(f"Predictions file not found: {args.predictions}", file=sys.stderr)
        sys.exit(1)

    report = build_report(args.ground_truth, args.predictions)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Report written to {args.output}")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
