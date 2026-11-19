"""
Sarvam AI API client for Pratibimb.
Wraps Document AI (Extract + Digitise) and Sarvam-105B chat calls.
All calls are async; job-based endpoints poll until completion or timeout.

Verify model IDs and endpoint paths at https://docs.sarvam.ai before production use.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
from pathlib import Path
from typing import Any, Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

import structlog

log = structlog.get_logger(__name__)

SARVAM_BASE_URL = os.getenv("SARVAM_BASE_URL", "https://api.sarvam.ai")
SARVAM_API_KEY = os.getenv("SARVAM_API_KEY", "")

# Polling config
POLL_INTERVAL_SECONDS = 2.0
POLL_MAX_ATTEMPTS = 30          # up to ~60 s before giving up


class SarvamError(Exception):
    """Raised when a Sarvam API call fails irrecoverably."""


class SarvamClient:
    """
    Async Sarvam AI API client.

    Usage:
        async with SarvamClient() as client:
            result = await client.extract(image_bytes, schema, screenshot_type)
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 60.0,
    ) -> None:
        self._api_key = api_key or SARVAM_API_KEY
        self._base_url = (base_url or SARVAM_BASE_URL).rstrip("/")
        self._timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "SarvamClient":
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={
                "api-subscription-key": self._api_key,
                "Content-Type": "application/json",
            },
            timeout=self._timeout,
        )
        return self

    async def __aexit__(self, *_: Any) -> None:
        if self._client:
            await self._client.aclose()

    # ------------------------------------------------------------------ #
    # Internal helpers                                                      #
    # ------------------------------------------------------------------ #

    def _encode_image(self, image_bytes: bytes) -> str:
        return base64.b64encode(image_bytes).decode("utf-8")

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def _post(self, path: str, payload: dict) -> dict:
        assert self._client, "Use SarvamClient as an async context manager."
        resp = await self._client.post(path, json=payload)
        if resp.status_code not in (200, 201, 202):
            log.error("sarvam_api_error", path=path, status=resp.status_code, body=resp.text[:500])
            raise SarvamError(f"Sarvam API {path} returned {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    async def _poll_job(self, job_id: str) -> dict:
        """Poll a Document AI job until it completes or we exhaust retries."""
        for attempt in range(POLL_MAX_ATTEMPTS):
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
            resp = await self._client.get(f"/v1/document-ai/jobs/{job_id}")
            if resp.status_code != 200:
                log.warning("sarvam_poll_non200", job_id=job_id, status=resp.status_code)
                continue
            data = resp.json()
            status = data.get("status", "")
            if status == "completed":
                return data
            if status in ("failed", "error"):
                raise SarvamError(f"Sarvam job {job_id} failed: {data}")
            log.debug("sarvam_job_pending", job_id=job_id, attempt=attempt, status=status)
        raise SarvamError(f"Sarvam job {job_id} timed out after {POLL_MAX_ATTEMPTS} polls.")

    # ------------------------------------------------------------------ #
    # Public API                                                            #
    # ------------------------------------------------------------------ #

    async def extract(
        self,
        image_bytes: bytes,
        schema: dict,
        screenshot_type: str = "OTHER",
        language_hint: Optional[str] = None,
    ) -> dict:
        """
        Call Document AI Extract with a schema and return extracted fields.
        Returns dict with keys: job_id, fields, raw_response, latency_ms
        """
        import time
        t0 = time.monotonic()

        payload = {
            "model": "sarvam-vision-1.5",
            "mode": "extract",
            "image": self._encode_image(image_bytes),
            "schema": schema,
            "metadata": {
                "screenshot_type": screenshot_type,
                **({"language_hint": language_hint} if language_hint else {}),
            },
        }

        try:
            response = await self._post("/v1/document-ai/jobs", payload)
            job_id = response.get("job_id") or response.get("id")

            if job_id:
                # Async job — poll for result
                result = await self._poll_job(job_id)
                fields = result.get("output", {}).get("fields", {})
            else:
                # Synchronous response (some endpoints return inline)
                fields = response.get("fields", response.get("output", {}))
                job_id = response.get("request_id", "sync")

            latency_ms = int((time.monotonic() - t0) * 1000)
            log.info("sarvam_extract_done", job_id=job_id, latency_ms=latency_ms, type=screenshot_type)
            return {"job_id": job_id, "fields": fields, "raw_response": response, "latency_ms": latency_ms}

        except SarvamError:
            raise
        except Exception as exc:
            log.error("sarvam_extract_unexpected", error=str(exc))
            raise SarvamError(f"Extract failed: {exc}") from exc

    async def digitise(self, image_bytes: bytes) -> dict:
        """
        Call Document AI Digitise for full OCR (raw text extraction).
        Returns dict with keys: job_id, text, latency_ms
        """
        import time
        t0 = time.monotonic()

        payload = {
            "model": "sarvam-vision-1.5",
            "mode": "digitise",
            "image": self._encode_image(image_bytes),
        }

        try:
            response = await self._post("/v1/document-ai/jobs", payload)
            job_id = response.get("job_id") or response.get("id")

            if job_id:
                result = await self._poll_job(job_id)
                text = result.get("output", {}).get("text", "")
            else:
                text = response.get("text", response.get("output", ""))
                job_id = response.get("request_id", "sync")

            latency_ms = int((time.monotonic() - t0) * 1000)
            log.info("sarvam_digitise_done", job_id=job_id, latency_ms=latency_ms, chars=len(text))
            return {"job_id": job_id, "text": text, "latency_ms": latency_ms}

        except SarvamError:
            raise
        except Exception as exc:
            raise SarvamError(f"Digitise failed: {exc}") from exc

    async def classify_with_llm(self, raw_text: str, image_description: str = "") -> dict:
        """
        Use Sarvam-105B to classify an ambiguous screenshot.
        Returns dict: screenshot_type, confidence (0-1), reason (one line)
        """
        from intake.models import ScreenshotType

        type_values = [t.value for t in ScreenshotType]
        system_prompt = (
            "You are a screenshot classifier for an Indian metro ticketing system. "
            "Classify the screenshot into exactly one of these types: "
            f"{', '.join(type_values)}. "
            "Reply with JSON only: {\"screenshot_type\": \"...\", \"confidence\": 0.0, \"reason\": \"one line\"}. "
            "Use OTHER when genuinely unsure. Never guess. Never use the words fraud or verified."
        )
        user_message = f"Screenshot raw text:\n{raw_text}\n\nAdditional context: {image_description}"

        payload = {
            "model": "sarvam-105b",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "temperature": 0.1,
            "max_tokens": 128,
        }

        try:
            response = await self._post("/v1/chat/completions", payload)
            content = response["choices"][0]["message"]["content"].strip()
            # Strip markdown fences if present
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
            return {"screenshot_type": "OTHER", "confidence": 0.0, "reason": f"classification error: {exc}"}

    async def translate(self, text: str, target_language_code: str, source_language_code: str = "en") -> str:
        """
        Translate text using Sarvam Translate (Mayura).
        target_language_code: BCP-47 codes like 'kn-IN', 'hi-IN', 'en-IN'
        Returns translated string; falls back to original on error.
        """
        if not text.strip():
            return text
        payload = {
            "input": text,
            "source_language_code": source_language_code,
            "target_language_code": target_language_code,
            "speaker_gender": "Male",
            "mode": "formal",
            "model": "mayura:v1",
            "enable_preprocessing": True,
        }
        try:
            response = await self._post("/v1/translate", payload)
            return response.get("translated_text", text)
        except SarvamError:
            log.warning("sarvam_translate_failed", target=target_language_code)
            return text
