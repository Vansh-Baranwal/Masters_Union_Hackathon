# Day-0 Feasibility Report

> **Status:** template — fill in after running real tickets through the pipeline.

## Objective

Verify that Sarvam Vision + local QR decode can read and link real Namma Metro screenshots before committing to the full build.

## Test plan

1. Buy 5 tickets across at least two channels (WhatsApp bot, Namma Metro app).  
2. Cancel one ticket to generate a refund.  
3. Screenshot everything: ticket QR, UPI success, bank SMS, bot error, refund SMS.  
4. Run each through `run_extraction_pipeline()` with `SARVAM_API_KEY` set.  
5. Record fields extracted, misses, wrong values, and latency.

## Results

| Screenshot | Channel | Fields extracted | Misses | Wrong values | Latency (ms) |
|---|---|---|---|---|---|
| *(fill in)* | | | | | |

## QR decode

| Test | Result |
|---|---|
| Original QR | |
| Cropped QR | |
| Recompressed (WhatsApp) | |
| Screenshot-of-screenshot | |

## Cross-source linking

| Payment screenshot | Ticket screenshot | Shared identifier found? |
|---|---|---|
| *(fill in)* | | |

## Sarvam Vision suitability

| Metric | Result |
|---|---|
| Usable fields on English screenshots | |
| Usable fields on Kannada screenshots | |
| Avg latency per job (ms) | |
| Async vs sync response | |

## Go / No-go decision

| Decision | Condition | Status |
|---|---|---|
| Proceed with exact linking | Reliable shared identifiers exist | *(fill in)* |
| Proceed with inferred linking | Only contextual matching works | *(fill in)* |
| Reconsider scope | Essential fields cannot be extracted | *(fill in)* |
| Sarvam fallback | Vision fails → Digitise + 105B | *(fill in)* |

## Notes

*(Add observations here)*
