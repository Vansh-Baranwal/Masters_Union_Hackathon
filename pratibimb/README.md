# Pratibimb 🪞

**Every screenshot gets an owner, a trail and an honest label for how well it is supported.**

*REWIRED hackathon · Constraint B: MIRROR*

> Pratibimb: Hindi for "reflection". The screenshot is the reflection; we keep the record behind it.

---

## Quick start

```bash
# 1. Clone and enter the project
cd pratibimb

# 2. Create a virtual environment and install dependencies
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS / Linux
pip install -r requirements.txt

# 3. Configure secrets
copy .env.example .env
# Edit .env — set SARVAM_API_KEY and TELEGRAM_BOT_TOKEN at minimum

# 4. Start the API server
python main.py

# 5. (New terminal) Seed demo data
python seed_demo.py

# 6. (New terminal) Open the coordinator dashboard
streamlit run dashboard/app.py

# 7. (Optional) Start the Telegram bot
python main.py --mode bot
```

---

## What it does

Namma Metro sells QR tickets through a WhatsApp chatbot. When something goes wrong — payment debited but no ticket, refund not received, duplicate claims — the evidence lives only in scattered screenshots. Pratibimb turns those screenshots into a system of record.

| Person | Sends | Gets |
|---|---|---|
| **Traveller** | Any screenshot to the bot | A reply card in their language: ticket received, payment found, more evidence needed, or could not read |
| **Coordinator** | — | Roster, exceptions inbox, evidence trail, claim sheet |
| **Finance** | — | CSV / XLSX export with link types and evidence levels |

---

## Architecture

```
Traveller screenshot
        │
        ▼
  Telegram Bot (intake/channel.py)
        │
        ├─► Local QR decode  (intake/qr_decoder.py)
        ├─► Sarvam Digitise  (extraction/sarvam_client.py)
        ├─► Classifier       (extraction/classifier.py)
        └─► Sarvam Extract   (extraction/pipeline.py)
                │
                ▼
         Evidence + Interpretation records
                │
                ├─► Duplicate detection  (core/duplicates.py)  3 layers
                ├─► Linking engine       (core/linking.py)      EXACT/INFERRED/MANUAL/UNMATCHED
                ├─► Trust assessment     (core/trust.py)        evidence levels + machine states
                └─► Append-only store   (core/store.py)         hash chain
                         │
              ┌──────────┴──────────┐
              ▼                     ▼
       FastAPI (api/)        Reply card PNG
       /trips /inbox         (cards/generator.py)
       /records /decisions   sent back to traveller
       /audit /export
              │
              ▼
   Streamlit Dashboard (dashboard/app.py)
   Roster · Inbox · Trail · Decisions · Export · Audit
```

---

## Repository layout

```
pratibimb/
├── main.py                  Entry point (API / bot / both)
├── seed_demo.py             Demo data seeder
├── requirements.txt
├── pyproject.toml
├── .env.example
│
├── intake/                  Channel ingestion, hashing, QR, normalisers
│   ├── channel.py           Telegram bot
│   ├── processor.py         Evidence record builder
│   ├── fingerprint.py       SHA-256 + pHash + aHash
│   ├── qr_decoder.py        Local pyzbar QR decoder
│   ├── normalisers.py       Amount, timestamp, UTR, name masking
│   └── models.py            Pydantic models (EvidenceRecord, InterpretationRecord, …)
│
├── extraction/              Sarvam clients, classifier, field builder
│   ├── sarvam_client.py     Async Sarvam Vision / Digitise / 105B / Translate
│   ├── classifier.py        Rule-based + LLM-escalation classifier
│   ├── field_builder.py     Merge Sarvam output + QR data into typed fields
│   ├── pipeline.py          Full extraction pipeline per image
│   └── schemas/             One JSON schema per screenshot type (9 files)
│
├── core/                    Append-only store, dedup, linking, trust
│   ├── database.py          SQLAlchemy async engine + session factory
│   ├── models.py            ORM models (evidence, interpretations, relationships, decisions, …)
│   ├── store.py             All DB writes — append-only with hash chain
│   ├── duplicates.py        3-layer duplicate detection
│   ├── linking.py           EXACT / INFERRED / MANUAL / UNMATCHED linker
│   └── trust.py             Trust assessment, machine states, adaptive challenge
│
├── api/                     FastAPI application
│   ├── app.py               App factory + lifespan
│   ├── schemas.py           Pydantic request/response schemas
│   ├── dependencies.py      FastAPI dependency injectors
│   └── routers/
│       ├── trips.py         POST /trips, GET /trips/{id}/summary, POST /trips/{id}/join-code
│       ├── inbox.py         GET /trips/{id}/inbox
│       ├── records.py       GET /records/{id}/trail
│       ├── decisions.py     POST /decisions
│       ├── challenge.py     POST /challenge/{id}
│       ├── audit.py         GET /audit/verify
│       ├── export.py        GET /export/claims
│       └── ingest.py        POST /ingest  (used by bot layer)
│
├── cards/                   PIL reply-card generator
│   ├── generator.py         Renders PNG card for each verdict
│   └── translations.py      Pre-translated fixed strings (en / hi-IN / kn-IN)
│
├── dashboard/               Streamlit coordinator UI
│   └── app.py               Roster · Inbox · Trail · Decisions · Export · Audit
│
├── eval/                    Evaluation harness and scorer
│   ├── scorer.py            Classification, field, linking, false-accept metrics
│   ├── harness.py           Runs pipeline over a labelled image folder
│   └── data/calibration/
│       └── manifest.jsonl   Sample manifest (replace with real labelled data)
│
├── fixtures/                Hand-made Interpretation records for tests + demo
│   ├── loader.py
│   └── *.json               One fixture per screenshot scenario
│
├── tests/
│   ├── conftest.py
│   ├── test_classifier.py
│   ├── test_store.py
│   ├── test_duplicates.py
│   ├── test_trust.py
│   ├── test_linking.py
│   ├── test_normalisers.py
│   ├── test_scorer.py
│   └── test_cards.py
│
└── docs/
    ├── day0_feasibility_report.md
    ├── privacy_and_retention.md
    └── threat_model.md
```

---

## API reference (key endpoints)

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/trips` | Create a trip |
| `POST` | `/trips/{id}/join-code` | Refresh join code |
| `GET`  | `/trips/{id}/summary` | Roster and counts |
| `GET`  | `/trips/{id}/inbox` | Exceptions only, with reasons |
| `GET`  | `/records/{id}/trail` | Full evidence trail for one item |
| `POST` | `/decisions` | Approve / reject / request proof / link manually |
| `POST` | `/challenge/{id}` | Trigger adaptive evidence challenge |
| `GET`  | `/audit/verify` | Hash-chain integrity check |
| `GET`  | `/export/claims?trip_id=&fmt=json\|csv\|xlsx` | Claim sheet export |
| `POST` | `/ingest` | Submit a screenshot programmatically |

Interactive docs at `http://localhost:8000/docs` when the server is running.

---

## Running tests

```bash
pytest tests/ -v
```

---

## Evidence levels and relationship types

**Evidence levels** (per attribute, never global):

| Level | Meaning |
|---|---|
| `extracted` | Fields successfully extracted from submitted evidence |
| `corroborated` | Two independent sources agree on the attribute |
| `independently_verified` | An authoritative external source confirmed it |

**Relationship types:**

| Type | Basis | Auto-clear? |
|---|---|---|
| `EXACT` | Shared UTR / ticket_id / order_id / QR payload | Eligible |
| `INFERRED` | Amount + timestamp + stations agree | Never — always reviewed |
| `MANUAL` | Coordinator explicitly linked | n/a |
| `UNMATCHED` | Insufficient evidence | Preserved and shown |

---

## Core principle

> Pratibimb does not establish truth. It establishes ownership, evidence relationships, consistency and accountability.

- A screenshot is a **claim**, not proof.
- The system never says "fraud" and never says "verified" unless an authoritative source confirmed that specific attribute.
- It says *extracted*, *corroborated*, *unverified*, *needs review*.

---

## Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11, FastAPI, SQLAlchemy async |
| Database | SQLite (demo) / Postgres (production) |
| Extraction | Sarvam Vision 1.5, Sarvam-105B, Sarvam Translate |
| QR + images | pyzbar, imagehash, Pillow, OpenCV |
| Bot | python-telegram-bot |
| Dashboard | Streamlit, Plotly |
| Export | openpyxl |

---

*Status: build complete (v1). Day-0 feasibility test results to be filled in `docs/day0_feasibility_report.md`.*
