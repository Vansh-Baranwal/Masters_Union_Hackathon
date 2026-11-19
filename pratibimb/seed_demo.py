"""
Demo seeder — loads the hand-made fixtures into a fresh database so the
dashboard and demo flow work immediately without real images or API calls.

Run once after `python main.py` has initialised the DB:
    python seed_demo.py

Creates:
  - 1 trip  "Demo Trip — Namma Metro"  (coordinator: demo-coord)
  - 3 travellers
  - 9 evidence + interpretation records (one per fixture)
  - Relationships that mirror the spec demo scenario:
      UPI Success ←EXACT→ Ticket QR   (shared order_id)
      Bank SMS    ←EXACT→ UPI Success  (shared UTR)
      UPI Failed  → UNMATCHED (no ticket)
      Suspect     → UNMATCHED (scam)
  - 1 coordinator decision (approve the corroborated pair)
"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone

from core.database import init_db, get_session
from core.store import Store
from fixtures.loader import load_fixture
from intake.models import EvidenceRecord, ScreenshotType

FIXTURE_SENDERS = {
    "ticket_qr_01":           "traveller-alice",
    "upi_success_01":         "traveller-alice",
    "bank_sms_01":            "traveller-alice",
    "upi_failed_01":          "traveller-bob",
    "bot_error_01":           "traveller-bob",
    "refund_notice_01":       "traveller-bob",
    "suspect_notice_01":      "traveller-carol",
    "other_01":               "traveller-carol",
    "ticket_qr_duplicate_01": "traveller-carol",   # reuse scenario
}

TRAVELLERS = [
    ("traveller-alice", "Alice M.", "en"),
    ("traveller-bob",   "Bob R.",   "en"),
    ("traveller-carol", "Carol S.", "kn-IN"),
]

TRIP_NAME = "Demo Trip — Namma Metro"
COORD_ID  = "demo-coord"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fake_fingerprints(fixture_name: str) -> dict:
    """Deterministic fake fingerprints keyed on fixture name."""
    import hashlib
    h = hashlib.sha256(fixture_name.encode()).hexdigest()
    return {
        "sha256": h,
        "phash":  h[:16],
        "ahash":  h[16:32],
    }


async def seed() -> None:
    await init_db()

    async with get_session() as session:
        store = Store(session)

        # 1. Create trip
        trip = await store.create_trip(TRIP_NAME, COORD_ID)
        print(f"Trip created: {trip.trip_id}  join_code={trip.join_code}")

        # 2. Add travellers
        for sender_id, display_name, lang in TRAVELLERS:
            await store.add_traveller(trip.trip_id, sender_id, display_name, lang)
        print(f"Travellers added: {[t[0] for t in TRAVELLERS]}")

        # 3. Load fixtures and create evidence + interpretation records
        ev_id_map: dict[str, str] = {}  # fixture_name → evidence_id

        for fixture_name, sender_id in FIXTURE_SENDERS.items():
            interp = load_fixture(fixture_name)
            fp = _fake_fingerprints(fixture_name)

            ev_record = EvidenceRecord(
                evidence_id=str(uuid.uuid4()),
                trip_id=trip.trip_id,
                sender_id=sender_id,
                channel="demo_seed",
                received_at=interp.created_at or _now(),
                file_ref=f"./data/raw_images/{fixture_name}.bin",
                sha256=fp["sha256"],
                phash=fp["phash"],
                ahash=fp["ahash"],
                status="processed",
            )
            await store.add_evidence(ev_record)

            # Remap the interp to this new evidence_id
            interp.evidence_id = ev_record.evidence_id
            interp.interp_id   = str(uuid.uuid4())
            await store.add_interpretation(interp)

            ev_id_map[fixture_name] = ev_record.evidence_id
            print(f"  Seeded: {fixture_name} → ev={ev_record.evidence_id[:8]}…")

        # 4. Create relationships
        # Alice's UPI Success ←EXACT→ Ticket QR (shared order_id ORD-2024-00123)
        await store.add_relationship(
            from_id=ev_id_map["upi_success_01"],
            to_id=ev_id_map["ticket_qr_01"],
            rel_type="EXACT",
            basis=["order_id"],
            score=1.0,
            created_by="system",
            plain_reason="Shared order_id: ORD-2024-00123",
        )
        # Bank SMS ←EXACT→ UPI Success (shared UTR)
        await store.add_relationship(
            from_id=ev_id_map["bank_sms_01"],
            to_id=ev_id_map["upi_success_01"],
            rel_type="EXACT",
            basis=["utr"],
            score=1.0,
            created_by="system",
            plain_reason="Shared UTR: 401234567890",
        )
        # UPI Failed → UNMATCHED
        await store.add_relationship(
            from_id=ev_id_map["upi_failed_01"],
            to_id=ev_id_map["upi_failed_01"],
            rel_type="UNMATCHED",
            basis=["no_match"],
            score=0.0,
            created_by="system",
            plain_reason="No matching ticket found for failed payment.",
        )
        # Bot error ←INFERRED→ UPI Failed (same amount + close timestamp)
        await store.add_relationship(
            from_id=ev_id_map["bot_error_01"],
            to_id=ev_id_map["upi_failed_01"],
            rel_type="INFERRED",
            basis=["amount", "timestamp_delta=420s"],
            score=0.70,
            created_by="system",
            plain_reason="Same trip amount and close timestamp suggest same booking attempt.",
        )
        # Refund ←INFERRED→ Bot error (shared order_id text reference)
        await store.add_relationship(
            from_id=ev_id_map["refund_notice_01"],
            to_id=ev_id_map["bot_error_01"],
            rel_type="INFERRED",
            basis=["amount"],
            score=0.65,
            created_by="system",
            plain_reason="Refund amount matches failed payment amount.",
        )
        # Duplicate ticket (carol reusing alice's ticket)
        await store.add_relationship(
            from_id=ev_id_map["ticket_qr_duplicate_01"],
            to_id=ev_id_map["ticket_qr_01"],
            rel_type="EXACT",
            basis=["ticket_id", "qr_payload"],
            score=1.0,
            created_by="system",
            plain_reason="Duplicate ticket submission: same ticket_id NM-2024-00123 from different sender.",
        )
        print("Relationships seeded.")

        # 5. Open cases for exceptions
        for fname in ("upi_failed_01", "suspect_notice_01", "ticket_qr_duplicate_01"):
            await store.open_case(
                trip_id=trip.trip_id,
                evidence_id=ev_id_map[fname],
                sender_id=FIXTURE_SENDERS[fname],
                reason={
                    "upi_failed_01":          "Payment failed — no ticket issued.",
                    "suspect_notice_01":      "Screenshot matches scam-message patterns.",
                    "ticket_qr_duplicate_01": "Ticket already submitted by another traveller.",
                }[fname],
            )
        print("Cases opened for exceptions.")

        # 6. Coordinator approves Alice's corroborated submission
        await store.add_decision(
            subject_ref=ev_id_map["upi_success_01"],
            action="approved",
            decided_by=COORD_ID,
            reason="Payment and ticket linked by shared order_id. Approved for reimbursement.",
        )
        print("Demo coordinator decision recorded.")

        print(f"\n✅  Demo seeded successfully.")
        print(f"   Trip ID  : {trip.trip_id}")
        print(f"   Join code: {trip.join_code}")
        print(f"   Open the dashboard and enter the Trip ID above.")


if __name__ == "__main__":
    asyncio.run(seed())
