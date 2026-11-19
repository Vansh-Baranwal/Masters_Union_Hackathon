# Pratibimb — Judge Demo Guide

**Tagline:** Every screenshot gets an owner, a trail and an honest label for how well it is supported.

**Constraint:** B (MIRROR) — the way into the system must be a screenshot.

**Problem in one line:** When a group travels by metro, the coordinator has no system of record — just 40 screenshots scattered across WhatsApp chats.

---

## What to have ready before the demo

| Item | Detail |
|---|---|
| Laptop | Dashboard open at http://localhost:8501 |
| Phone | Telegram bot open (`@Pratibimb_bglr_metro_bot`) |
| Screenshots | 3–4 real or synthetic: a metro QR ticket, a UPI success, a bank SMS, optionally a bot error |
| Second phone / judge's phone | To show a live submission from someone else |

---

## Pre-demo checklist (run once, 2 minutes before)

```bash
# Terminal 1 — API server
cd "D:\Some_stuffs\Road to Milky Way\Masters_Union_Hackathon\pratibimb"
python main.py --mode api

# Terminal 2 — Telegram bot
python main.py --mode bot

# Terminal 3 — Dashboard
python -m streamlit run dashboard/app.py --browser.gatherUsageStats false
```

Confirm in dashboard sidebar: **API ✅ online**

---

## Demo flow (~4 minutes)

---

### Step 1 — Set the scene (20 seconds)

> "India runs group travel on WhatsApp. A coordinator books 40 metro tickets. What comes next is entirely manual — people forward screenshots to a group chat, the coordinator scrolls through 40 chats, checks who has a ticket, whose payment failed, and who is claiming reimbursement twice. There is no system. There is just a person with a spreadsheet and a headache."
>
> "Pratibimb puts a system of record behind the screenshot habit — without changing the habit."

---

### Step 2 — Create a trip (30 seconds)

**Dashboard → sidebar → ➕ Create new trip**

- Trip name: `Judge Demo Trip`
- Coordinator ID: `demo-coord`
- Click **Create**

> "Every group journey is a trip. The coordinator creates one and gets a join code. That code is how the system knows which screenshots belong together."

Copy the **join code** shown. Keep the **Trip ID** in the sidebar.

---

### Step 3 — Join the trip from Telegram (30 seconds)

On your phone, open the bot and send:

```
/join <JOINCODE>
```

> "Travellers do nothing different from their normal WhatsApp habit — except they send to this one number instead. No app download, no login, no form."

If a judge wants to join from their phone, share the join code now.

---

### Step 4 — Send a metro ticket screenshot (45 seconds)

Send the **Namma Metro QR ticket screenshot** to the bot.

The bot will:
1. Acknowledge receipt immediately ("📥 Received — filing your screenshot…")
2. After ~10–15 seconds (Sarvam API processing): send back a **reply card** (PNG image)

Point out on the card:
- **Verdict** — "Ticket received" (green) or "Recorded" (blue)
- **Evidence level** — extracted / corroborated
- **Ref** — the 8-character evidence ID

> "The bot reads the screenshot, extracts the ticket ID, timestamp and stations, files it as an immutable record with a hash, and sends back a card in the traveller's language."

**Switch to dashboard → 🏠 Overview**

> "Meanwhile, the coordinator's dashboard updates. One screenshot filed, evidence level extracted."

---

### Step 5 — Send a UPI payment screenshot (45 seconds)

Send the **UPI success screenshot** to the bot.

> "Now send the payment screenshot. The system tries to link it to the ticket."

After the reply card arrives:

**Dashboard → 📥 Inbox**

If the system finds a shared identifier (order ID or UTR), the inbox will show the payment as **corroborated** (linked to the ticket). If it cannot find a shared ID, it opens a case and asks for more evidence.

> "The coordinator only sees the exceptions — not all 40 submissions. If everything is corroborated, the inbox is empty."

---

### Step 6 — Duplicate test (30 seconds)

Send the **same QR ticket screenshot again** (or have the judge send it from their phone).

The bot will reply with the card **plus** a warning:

```
⚠️ This screenshot matches a previous submission (resend / semantic, ref: xxxxxxxx).
```

> "If the same ticket is submitted twice — by the same person or someone else — the system catches it immediately. Three independent layers: exact file hash, shared ticket ID, and perceptual visual similarity. The coordinator is notified."

---

### Step 7 — View the evidence trail (30 seconds)

**Dashboard → 🔍 Trail**

Paste the evidence ID from the reply card ref.

> "Every item has a complete, immutable history — what was submitted, what was extracted, how confident we are in each field, what it was linked to, and every decision ever made about it."

Point out:
- **Evidence record** — SHA-256, pHash, channel, timestamp
- **Interpretation** — screenshot type, confidence, extracted fields with per-field confidence
- **Relationships** — EXACT / INFERRED / MANUAL / UNMATCHED with the basis shown
- **Decisions** — empty until the coordinator acts

---

### Step 8 — Make a coordinator decision (20 seconds)

**Dashboard → ✅ Decisions**

- Evidence ID: paste the ticket evidence ID
- Action: **Approved**
- Coordinator ID: `demo-coord`
- Reason: "Ticket and payment corroborated by shared order ID."
- Click **Submit**

> "The coordinator's decision is permanently recorded with a hash of exactly what they saw. It cannot be edited or deleted. This is the accountability layer."

---

### Step 9 — Export the claim sheet (20 seconds)

**Dashboard → 📤 Export → xlsx → Generate → Download**

Open the Excel file.

> "Finance or HR downloads this. Each row has the screenshot type, extracted fields, evidence level, relationship type, and coordinator decision. No manual cross-referencing."

---

### Step 10 — Tamper-proof audit (20 seconds)

**Dashboard → 🔒 Audit → Run integrity check**

Should show: ✅ Chain intact — N records verified.

> "Every record write is chained: each hash is derived from the record contents plus the previous hash. If any row is edited after the fact, the chain breaks at exactly that point. This gives tamper evidence — not prevention, but proof."

**Optional break-me demo:** Directly edit a row in `pratibimb.db` using DB Browser for SQLite, then run the check again. It will report the exact sequence number where the chain broke.

---

## Likely judge questions and answers

**Q: This is just a Telegram bot — where's the system of record?**
> The bot is only the door. The ledger, the hash chain, the duplicate engine, the linking logic, and the coordinator dashboard are the system. The bot could be replaced by WhatsApp Business API or any other channel tomorrow.

**Q: What stops someone from faking a screenshot?**
> Nothing stops a single fake — that is honest. What the system does: it requires a second independent source that agrees (corroboration). An adaptive challenge asks for the smallest extra item that would conflict with a weak claim. And it labels every verdict honestly — extracted, corroborated, needs review — never "verified." The coordinator always makes the final call.

**Q: Does it work for other processes beyond metro ticketing?**
> Same engine works for housing society dues, event registrations, expense claims, school fee receipts — any process where the proof of payment is a screenshot. The screenshot types and schemas change; the core does not.

**Q: What's the Sarvam AI integration?**
> Sarvam Vision reads the screenshot and extracts structured fields (amount, timestamp, ticket ID, UTR). Sarvam-105B classifies ambiguous screenshots. Sarvam Translate sends the reply card back in Kannada or Hindi if the traveller set that preference. The metro bot itself runs in English and Kannada — so Kannada OCR support is not optional.

**Q: What happens when Sarvam is slow or down?**
> The system degrades gracefully. If extraction fails, the screenshot is still filed with its fingerprints and the raw OCR text. The coordinator sees it as "unreadable" in the inbox and can manually review or request a resend. Nothing is lost.

---

## System summary (one slide worth)

| Layer | What it does |
|---|---|
| **Intake** | Receives screenshot, computes SHA-256 + pHash + aHash, decodes QR locally, saves raw image |
| **Extraction** | Sarvam Vision OCR + per-type schema extraction + rule-based classifier with LLM fallback |
| **Duplicate detection** | 3 layers: exact SHA-256, semantic (shared ticket_id/UTR), perceptual (pHash Hamming distance) |
| **Linking engine** | EXACT (shared identifier) → INFERRED (contextual) → MANUAL → UNMATCHED. Never guesses. |
| **Trust assessment** | Per-attribute evidence levels: extracted → corroborated → independently verified. No global verdict. |
| **Append-only store** | Every record immutable. Corrections are new rows. Hash chain detects tampering. |
| **Coordinator tools** | Dashboard (roster, inbox, trail, decisions, export, audit). API-first so any frontend works. |
| **Reply cards** | PNG card per submission, generated in English / Hindi / Kannada. Users screenshot the card too. |

---

*Pratibimb: Hindi for "reflection". The screenshot is the reflection; we keep the record behind it.*
