# Threat Model

## What Pratibimb defends against

| Threat | Mitigation |
|---|---|
| **Accidental omission** — traveller forgets to send one screenshot | Adaptive evidence challenge asks for the smallest extra item; claim stays open, not rejected |
| **Single pre-made fake** — one fabricated payment screenshot | Corroboration check: system looks for a second independent source (ticket + payment) |
| **Simple reuse** — same screenshot sent by two different travellers | Exact SHA-256 and semantic duplicate detection; flagged as `EXACT_REUSE` for coordinator review |
| **Cropped or recompressed reuse** | Perceptual hash (pHash / aHash) within Hamming threshold |
| **Out-of-window ride** | Timestamp extracted and shown; coordinator sees the date and decides |
| **Tampered past record** | Hash chain: `record_hash = SHA256(record_json + prev_hash)`; `/audit/verify` detects any edited row |
| **Scam / phishing notice forwarded as genuine refund** | `SUSPECT_NOTICE` classifier pattern matches; never auto-cleared; coordinator notified |

## What Pratibimb does NOT defend against

| Threat | Reason |
|---|---|
| **Coordinated fake set** — attacker generates a full consistent payment + ticket + bank SMS set | Corroboration shows consistency, not truth; two fabricated items can agree |
| **Gate scan verification** | Pratibimb cannot see BMRCL gate records; "travelled" is the traveller's assertion |
| **Operator record confirmation** | No API to BMRCL backend; independently verified level not reachable without it |
| **Sarvam API compromise** | Extraction depends on a third-party API; a compromised API could return false fields |
| **Social engineering of coordinator** | Coordinator decisions are human; Pratibimb records them but cannot prevent bad decisions |

## Key principles

- Pratibimb never says "fraud". It says *needs_review*, *unmatched*, *suspect_pattern*.
- Pratibimb never says "verified" unless an authoritative external source confirmed the specific attribute.
- Every claim is labelled with how well it is supported, not whether it is true.
- The adaptive challenge raises the cost of a fake but does not end the threat.

## Out of scope

- Preventing a determined attacker who controls multiple channels and generates a full consistent fabricated set.
- Transport-layer security (use HTTPS in production; this is infrastructure, not application-level).
- Key management for image encryption (use a secrets manager in production, not `.env`).
