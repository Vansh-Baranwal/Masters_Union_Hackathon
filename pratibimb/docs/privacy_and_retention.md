# Privacy and Retention

## What is stored

| Data | Where | Retention |
|---|---|---|
| Raw image file | `data/raw_images/<evidence_id>.bin` | Encrypted at rest; deleted after `RAW_IMAGE_RETENTION_DAYS` from case closure |
| Extracted fields (masked) | Database — `interpretations.fields_json` | Kept as long as the trip record exists |
| Perceptual fingerprints | Database — `evidence.phash`, `evidence.ahash` | Kept indefinitely (no personal data) |
| SHA-256 hash | Database — `evidence.sha256` | Kept indefinitely |
| Payer name | Stored **masked** (e.g. `Me**a S.`) | Same as extracted fields |
| Full UTR / order ID | Stored in full (required for linking) | Same as extracted fields |
| Coordinator decisions | `decisions` table | Kept as long as the trip record exists |

## What the API returns

The coordinator API returns **fields, not images**. Raw image access requires an explicit request that is logged (`access_log` table).

Sensitive fields are masked at the API layer:
- Payer names: partial only
- UTR: returned in full only when a Decision requires it

## Raw image deletion

Triggered by the lifecycle worker (`DELETE` from `evidence.file_ref` path):
- After `RAW_IMAGE_RETENTION_DAYS` days from case closure or trip close.
- Deletion is logged in `access_log` with `requested_by = "lifecycle_worker"`.

## Third-party data flow

Screenshots are sent to the **Sarvam AI API** for extraction before field masking is applied. Before deployment:

1. Read Sarvam's data retention and residency terms at [docs.sarvam.ai](https://docs.sarvam.ai).
2. Confirm whether Sarvam stores request payloads and for how long.
3. Update the privacy notice shown to travellers before they send their first screenshot.

## Honest description

> "Pratibimb stores masked fields and perceptual fingerprints. Raw images are encrypted, access-logged, and deleted on a fixed schedule. We do not claim zero-knowledge — screenshots pass through Sarvam AI before masking."

## Open questions

- Exact retention period (currently controlled by `RAW_IMAGE_RETENTION_DAYS` env var). Needs sign-off from a privacy or legal reviewer before production.
- Whether Sarvam's residency is acceptable for the user population.
