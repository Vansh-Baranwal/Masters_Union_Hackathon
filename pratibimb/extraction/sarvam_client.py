"""
Sarvam AI API client for Pratibimb.

Verified against sarvamai SDK v0.1.46 and live API (19-Nov-2026):
  - Parse (OCR):   POST /doc-ai/v1/job/parse    → results at GET /doc-ai/v1/job/{id}/results
  - Extract:       POST /doc-ai/v1/job/extract  → results at GET /doc-ai/v1/job/{id}/results
  - Chat (LLM):    POST /v1/chat/completions
  - Translate:     POST /translate

All blocking SDK calls are wrapped in run_in_executor so they don't block the bot's event loop.
"""
from __future__ import annotations

import io
import json
import os
import time
from typing import Optional

import httpx
import structlog

log = structlog.get_logger(__name__)

SARVAM_API_KEY  = os.getenv("SARVAM_API_KEY", "")
SARVAM_BASE_URL = os.getenv("SARVAM_BASE_URL", "https://api.sarvam.ai")
POLL_INTERVAL   = 3     # seconds between status polls
POLL_TIMEOUT    = 90    # max seconds to wait for a job

TERMINAL_STATES = {"completed", "partially_completed", "failed", "rejected"}


class SarvamError(Exception):
    pass


def _headers() -> dict:
    return {"api-subscription-key": SARVAM_API_KEY}


def _get_sdk_client():
    try:
        from sarvamai import SarvamAI
    except ImportError:
        raise SarvamError("sarvamai not installed: pip install sarvamai")
    return SarvamAI(api_subscription_key=SARVAM_API_KEY)


def _poll(client, job_id: str):
    """Poll until terminal state; return final status object."""
    deadline = time.monotonic() + POLL_TIMEOUT
    while time.monotonic() < deadline:
        st = client.doc_ai.get_status(job_id=job_id)
        status = (st.status or "").lower()
        log.debug("sarvam_poll", job_id=job_id, status=status)
        if status in TERMINAL_STATES:
            return st
        time.sleep(POLL_INTERVAL)
    raise SarvamError(f"Job {job_id} timed out after {POLL_TIMEOUT}s")


def _fetch_results(job_id: str) -> dict:
    """
    Fetch job results via raw HTTP (bypasses SDK pydantic deserialization bug
    with the 'digitise' type tag in SDK v0.1.46).
    Endpoint: GET /doc-ai/v1/job/{job_id}/results
    """
    resp = httpx.get(
        f"{SARVAM_BASE_URL}/doc-ai/v1/job/{job_id}/results",
        headers=_headers(),
        timeout=30,
    )
    if resp.status_code != 200:
        raise SarvamError(f"Results fetch failed {resp.status_code}: {resp.text[:200]}")
    return resp.json()


def _blocks_to_text(data: dict) -> str:
    """Flatten all block texts from a results payload into a single string."""
    lines = []
    for doc in data.get("documents", []):
        for page in doc.get("pages", []):
            for block in page.get("blocks", []):
                t = block.get("text", "").strip()
                if t:
                    lines.append(t)
    return "\n".join(lines)


def _results_to_fields(data: dict) -> dict:
    """
    For extract jobs, the result fields live in documents[].pages[].blocks[]
    or in a top-level 'result' key depending on SDK version.
    Try both shapes.
    """
    # Shape 1: top-level result dict
    top = data.get("result")
    if isinstance(top, dict) and top:
        return top

    # Shape 2: blocks with field_name / value pairs
    fields: dict = {}
    for doc in data.get("documents", []):
        for page in doc.get("pages", []):
            for block in page.get("blocks", []):
                name = block.get("field_name") or block.get("key")
                val  = block.get("value") or block.get("text")
                if name and val is not None:
                    fields[name] = val
    return fields


# ─────────────────────────────────────────────────────────────────────────── #

class SarvamClient:
    """
    Async-compatible Sarvam API client.
    Blocking SDK calls run in a thread executor so they don't block asyncio.
    Can be used with both `async with` and plain `with`.
    """

    def __init__(self, api_key: Optional[str] = None, **_):
        self._api_key = api_key or SARVAM_API_KEY

    def __enter__(self): return self
    def __exit__(self, *_): pass
    async def __aenter__(self): return self
    async def __aexit__(self, *_): pass

    # ── Parse / digitise (full OCR) ──────────────────────────────────────── #

    async def digitise(self, image_bytes: bytes) -> dict:
        import asyncio
        return await asyncio.get_event_loop().run_in_executor(
            None, self._digitise_sync, image_bytes
        )

    def _digitise_sync(self, image_bytes: bytes) -> dict:
        t0 = time.monotonic()
        client = _get_sdk_client()
        try:
            job = client.doc_ai.parse(
                file=[("screenshot.jpg", io.BytesIO(image_bytes), "image/jpeg")],
            )
            st = _poll(client, job.job_id)
            text = ""
            if st.status.lower() in ("completed", "partially_completed"):
                data = _fetch_results(job.job_id)
                text = _blocks_to_text(data)
            latency_ms = int((time.monotonic() - t0) * 1000)
            log.info("sarvam_digitise_done", job_id=job.job_id, chars=len(text), latency_ms=latency_ms)
            return {"job_id": job.job_id, "text": text, "latency_ms": latency_ms}
        except SarvamError:
            raise
        except Exception as exc:
            raise SarvamError(f"Digitise failed: {exc}") from exc

    # ── Extract (structured fields) ───────────────────────────────────────── #

    async def extract(
        self,
        image_bytes: bytes,
        schema: dict,
        screenshot_type: str = "OTHER",
        language_hint: Optional[str] = None,
    ) -> dict:
        import asyncio
        return await asyncio.get_event_loop().run_in_executor(
            None, self._extract_sync, image_bytes, schema, language_hint
        )

    def _extract_sync(self, image_bytes: bytes, schema: dict, language_hint: Optional[str]) -> dict:
        t0 = time.monotonic()
        client = _get_sdk_client()
        try:
            job = client.doc_ai.extract(
                file=[("screenshot.jpg", io.BytesIO(image_bytes), "image/jpeg")],
                schema=json.dumps(schema),
                language=language_hint or "en-IN",
                output_format="json",
            )
            st = _poll(client, job.job_id)
            fields: dict = {}
            if st.status.lower() in ("completed", "partially_completed"):
                data = _fetch_results(job.job_id)
                fields = _results_to_fields(data)
            latency_ms = int((time.monotonic() - t0) * 1000)
            log.info("sarvam_extract_done", job_id=job.job_id, latency_ms=latency_ms, nfields=len(fields))
            return {"job_id": job.job_id, "fields": fields, "latency_ms": latency_ms}
        except SarvamError:
            raise
        except Exception as exc:
            raise SarvamError(f"Extract failed: {exc}") from exc

    # ── LLM classification ────────────────────────────────────────────────── #

    async def classify_with_llm(self, raw_text: str, image_description: str = "") -> dict:
        import asyncio
        return await asyncio.get_event_loop().run_in_executor(
            None, self._classify_sync, raw_text
        )

    def _classify_sync(self, raw_text: str) -> dict:
        from intake.models import ScreenshotType
        type_values = [t.value for t in ScreenshotType]
        system_prompt = (
            "You are a screenshot classifier for an Indian metro ticketing system. "
            f"Classify into exactly one of: {', '.join(type_values)}. "
            'Reply JSON only: {"screenshot_type":"...","confidence":0.0,"reason":"one line"}. '
            "Use OTHER when unsure. Never say fraud or verified."
        )
        try:
            resp = httpx.post(
                f"{SARVAM_BASE_URL}/v1/chat/completions",
                headers={**_headers(), "Content-Type": "application/json"},
                json={
                    "model": "sarvam-m",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": f"Screenshot text:\n{raw_text[:2000]}"},
                    ],
                    "temperature": 0.1,
                    "max_tokens": 128,
                },
                timeout=30,
            )
            if resp.status_code != 200:
                log.warning("sarvam_llm_error", status=resp.status_code, body=resp.text[:200])
                return {"screenshot_type": "OTHER", "confidence": 0.0, "reason": "llm_error"}
            content = resp.json()["choices"][0]["message"]["content"].strip()
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            parsed = json.loads(content)
            return {
                "screenshot_type": parsed.get("screenshot_type", "OTHER"),
                "confidence": float(parsed.get("confidence", 0.0)),
                "reason": parsed.get("reason", ""),
            }
        except Exception as exc:
            log.warning("sarvam_classify_failed", error=str(exc))
            return {"screenshot_type": "OTHER", "confidence": 0.0, "reason": str(exc)}

    # ── Translation ───────────────────────────────────────────────────────── #

    async def translate(self, text: str, target_language_code: str, source_language_code: str = "en-IN") -> str:
        if not text.strip():
            return text
        import asyncio
        return await asyncio.get_event_loop().run_in_executor(
            None, self._translate_sync, text, source_language_code, target_language_code
        )

    def _translate_sync(self, text: str, source: str, target: str) -> str:
        try:
            resp = httpx.post(
                f"{SARVAM_BASE_URL}/translate",
                headers={**_headers(), "Content-Type": "application/json"},
                json={
                    "input": text,
                    "source_language_code": source,
                    "target_language_code": target,
                    "speaker_gender": "Male",
                    "mode": "formal",
                    "model": "mayura:v1",
                    "enable_preprocessing": True,
                },
                timeout=20,
            )
            if resp.status_code == 200:
                return resp.json().get("translated_text", text)
            log.warning("sarvam_translate_failed", status=resp.status_code)
        except Exception as exc:
            log.warning("sarvam_translate_error", error=str(exc))
        return text
