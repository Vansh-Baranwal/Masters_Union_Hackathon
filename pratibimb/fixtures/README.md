# Fixtures

Hand-made Interpretation records for use in tests and demo without real images or Sarvam API calls.

Each `.json` file is a complete `InterpretationRecord`-shaped dict.
Load them with `fixtures/loader.py`.

## Files

| File | Type | Scenario |
|---|---|---|
| `ticket_qr_01.json` | TICKET_QR | Clean metro ticket, Indiranagar → MG Road |
| `upi_success_01.json` | UPI_SUCCESS | Matching payment for ticket_qr_01 |
| `bank_sms_01.json` | BANK_SMS | Bank debit SMS corroborating upi_success_01 |
| `upi_failed_01.json` | UPI_FAILED_PENDING | Payment failed — no ticket issued |
| `bot_error_01.json` | BOT_ERROR | Bot says booking failed, 7 working days refund |
| `refund_notice_01.json` | REFUND_NOTICE | Refund credited back after bot_error_01 |
| `suspect_notice_01.json` | SUSPECT_NOTICE | Fake refund message with click-here link |
| `other_01.json` | OTHER | Unclassified screenshot |
| `ticket_qr_duplicate_01.json` | TICKET_QR | Same ticket_id as ticket_qr_01, different sender — reuse scenario |
