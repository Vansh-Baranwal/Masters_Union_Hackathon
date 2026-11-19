"""
Evaluation harness — runs the extraction + classification pipeline over a
folder of labelled images and writes a predictions JSONL file for the scorer.

Usage:
    python -m eval.harness \
        --images   eval/data/calibration/ \
        --output   eval/results/predictions.jsonl \
        --split    test

The images directory must contain a manifest.jsonl file with one row per image:
    {"filename": "upi_success_01.png", "split": "test", "screenshot_type": "UPI_SUCCESS",
     "fields": {"amount": 40.0, "utr": "123456789012", ...}, "is_bad": false}
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import structlog

log = structlog.get_logger(__name__)


async def _run_one(image_path: Path, evidence_id: str) -> dict:
    from extraction.pipeline import run_extraction_pipeline
    image_bytes = image_path.read_bytes()
    interp = await run_extraction_pipeline(image_bytes, evidence_id)
    fields = interp.fields.model_dump() if interp.fields else {}
    return {
        "evidence_id": evidence_id,
        "screenshot_type": interp.screenshot_type.value,
        "type_confidence": interp.type_confidence,
        "fields": fields,
        "language_detected": interp.language_detected,
    }


async def run_harness(images_dir: Path, output_path: Path, split_filter: str) -> None:
    manifest_path = images_dir / "manifest.jsonl"
    if not manifest_path.exists():
        log.error("manifest_not_found", path=str(manifest_path))
        sys.exit(1)

    manifest = []
    with manifest_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                manifest.append(json.loads(line))

    rows = [r for r in manifest if r.get("split", "test") == split_filter]
    if not rows:
        log.warning("no_rows_for_split", split=split_filter)
        return

    output_path.parent.mkdir(parents=True, exist_ok=True)
    written = 0

    with output_path.open("w", encoding="utf-8") as out:
        for i, row in enumerate(rows):
            img_path = images_dir / row["filename"]
            if not img_path.exists():
                log.warning("image_not_found", path=str(img_path))
                continue
            ev_id = f"eval-{i:04d}"
            try:
                pred = await _run_one(img_path, ev_id)
                pred["split"] = row.get("split", "test")
                pred["is_bad"] = row.get("is_bad", False)
                out.write(json.dumps(pred) + "\n")
                written += 1
                log.info("processed", filename=row["filename"], type=pred["screenshot_type"])
            except Exception as exc:
                log.error("pipeline_error", filename=row["filename"], error=str(exc))

    log.info("harness_complete", written=written, total=len(rows))


def main():
    parser = argparse.ArgumentParser(description="Pratibimb evaluation harness")
    parser.add_argument("--images",  required=True, type=Path)
    parser.add_argument("--output",  required=True, type=Path)
    parser.add_argument("--split",   default="test")
    args = parser.parse_args()
    asyncio.run(run_harness(args.images, args.output, args.split))


if __name__ == "__main__":
    main()
