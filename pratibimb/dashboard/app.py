"""
Pratibimb coordinator dashboard — Streamlit app.

Pages:
  1. Roster        — all travellers + evidence counts per person
  2. Inbox         — exceptions only (needs_review / unreadable)
  3. Trail         — full evidence/interpretation/relationship/decision history
  4. Decisions     — approve / reject / request proof / link manually
  5. Claims export — download CSV or XLSX
  6. Audit         — hash-chain integrity check + tamper demo

Run with:
    streamlit run dashboard/app.py
"""
from __future__ import annotations

import asyncio
import io
import json
from typing import Optional

import pandas as pd
import plotly.express as px
import requests
import streamlit as st

API_BASE = "http://localhost:8000"


# ─── Helpers ──────────────────────────────────────────────────────────────── #

def api(method: str, path: str, **kwargs):
    url = f"{API_BASE}{path}"
    resp = getattr(requests, method)(url, **kwargs)
    if resp.status_code >= 400:
        st.error(f"API error {resp.status_code}: {resp.text[:300]}")
        return None
    return resp.json() if resp.headers.get("content-type", "").startswith("application/json") else resp


def _verdict_badge(verdict: str) -> str:
    colors = {
        "corroborated": "🟢",
        "extracted":    "🔵",
        "needs_review": "🟠",
        "unreadable":   "🔴",
    }
    return f"{colors.get(verdict, '⚪')} {verdict}"


def _rel_badge(rel_type: Optional[str]) -> str:
    if not rel_type:
        return "—"
    icons = {"EXACT": "🔗", "INFERRED": "〰️", "MANUAL": "✋", "UNMATCHED": "❓"}
    return f"{icons.get(rel_type, '')} {rel_type}"


# ─── Page: Roster ─────────────────────────────────────────────────────────── #

def page_roster(trip_id: str):
    st.header("Roster")
    summary = api("get", f"/trips/{trip_id}/summary")
    if not summary:
        return

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Travellers", summary["traveller_count"])
    col2.metric("Screenshots filed", summary["evidence_count"])
    col3.metric("Open cases", summary["open_case_count"])
    col4.metric("Trip status", summary["status"].upper())

    st.divider()
    st.subheader("Join code")
    st.code(summary.get("join_code") or "—", language=None)
    if st.button("Refresh join code"):
        result = api("post", f"/trips/{trip_id}/join-code")
        if result:
            st.success(f"New join code: **{result['join_code']}**")

    st.divider()
    st.subheader("Travellers")
    travellers = summary.get("travellers", [])
    if travellers:
        df = pd.DataFrame(travellers)[["display_name", "sender_id", "language_pref", "joined_at"]]
        df.columns = ["Name", "Sender ID", "Language", "Joined at"]
        st.dataframe(df, use_container_width=True)
    else:
        st.info("No travellers have joined yet.")


# ─── Page: Inbox ──────────────────────────────────────────────────────────── #

def page_inbox(trip_id: str):
    st.header("Exceptions Inbox")
    data = api("get", f"/trips/{trip_id}/inbox")
    if not data:
        return

    exceptions = data.get("exceptions", [])
    total = data.get("total_items", 0)
    st.caption(f"{len(exceptions)} exception(s) out of {total} total submissions")

    if not exceptions:
        st.success("No exceptions — all submissions are corroborated or recorded.")
        return

    # Summary donut
    verdict_counts = pd.Series([e["verdict"] for e in exceptions]).value_counts().reset_index()
    verdict_counts.columns = ["verdict", "count"]
    fig = px.pie(verdict_counts, names="verdict", values="count",
                 color_discrete_map={
                     "needs_review": "#C84B00", "unreadable": "#B71C1C",
                     "corroborated": "#1A7A4A", "extracted": "#424242",
                 },
                 hole=0.5, title="Exception breakdown")
    st.plotly_chart(fig, use_container_width=True)

    st.divider()
    for exc in exceptions:
        with st.expander(
            f"{_verdict_badge(exc['verdict'])}  ·  "
            f"{exc['screenshot_type']}  ·  "
            f"{exc['received_at'][:19]}  ·  sender: {exc['sender_id'][:12]}"
        ):
            col_a, col_b = st.columns(2)
            col_a.write(f"**Confidence:** {exc['type_confidence']:.0%}")
            col_a.write(f"**Link:** {_rel_badge(exc.get('relationship_type'))}")
            col_b.write(f"**Evidence level:** {exc['overall_level']}")
            col_b.write(f"**States:** {', '.join(exc['machine_states']) or '—'}")
            st.write(f"**Reason:** {exc['reason']}")
            if exc.get("needs_challenge"):
                if st.button("Send evidence challenge", key=f"ch_{exc['evidence_id']}"):
                    r = api("post", f"/challenge/{exc['evidence_id']}")
                    if r and r.get("challenge_sent"):
                        st.success("Challenge message queued.")
            st.caption(f"Ref: {exc['evidence_id']}")


# ─── Page: Trail ──────────────────────────────────────────────────────────── #

def page_trail():
    st.header("Evidence Trail")
    evidence_id = st.text_input("Evidence ID (or first 8 chars):").strip()
    if not evidence_id:
        st.info("Enter an evidence ID to view its full trail.")
        return

    # Accept short refs (prefix search not supported by API — tell user to use full ID)
    data = api("get", f"/records/{evidence_id}/trail")
    if not data:
        return

    st.subheader("Evidence")
    st.json(data["evidence"])

    st.subheader("Interpretations")
    for i, interp in enumerate(data["interpretations"]):
        label = f"[{i+1}] {interp['screenshot_type']}  conf={interp['type_confidence']:.0%}  {interp['created_at'][:19]}"
        with st.expander(label):
            st.json(interp)

    st.subheader("Relationships")
    if data["relationships"]:
        rel_df = pd.DataFrame([
            {
                "type": r["type"],
                "basis": ", ".join(r["basis"]),
                "score": r["score"],
                "reason": r["plain_reason"],
                "created_by": r["created_by"],
            }
            for r in data["relationships"]
        ])
        st.dataframe(rel_df, use_container_width=True)
    else:
        st.info("No relationships recorded yet.")

    st.subheader("Decisions")
    if data["decisions"]:
        dec_df = pd.DataFrame([
            {
                "action": d["action"],
                "decided_by": d["decided_by"],
                "reason": d["reason"],
                "created_at": d["created_at"][:19],
            }
            for d in data["decisions"]
        ])
        st.dataframe(dec_df, use_container_width=True)
    else:
        st.info("No coordinator decisions recorded yet.")


# ─── Page: Decisions ──────────────────────────────────────────────────────── #

def page_decisions():
    st.header("Record a Decision")
    with st.form("decision_form"):
        subject_ref = st.text_input("Evidence ID *")
        action = st.selectbox("Action *", ["approved", "rejected", "proof_requested", "linked_manually"])
        decided_by = st.text_input("Coordinator ID *")
        reason = st.text_area("Reason")
        link_to = st.text_input("Link to evidence ID (only for 'linked_manually')", value="")
        submitted = st.form_submit_button("Submit decision")

    if submitted:
        if not subject_ref or not decided_by:
            st.error("Evidence ID and Coordinator ID are required.")
            return
        payload = {
            "subject_ref": subject_ref,
            "action": action,
            "decided_by": decided_by,
            "reason": reason,
        }
        if action == "linked_manually" and link_to:
            payload["link_to_evidence_id"] = link_to
        result = api("post", "/decisions", json=payload)
        if result:
            st.success(f"Decision recorded: **{result['dec_id'][:12]}…** — {action}")


# ─── Page: Export ─────────────────────────────────────────────────────────── #

def page_export(trip_id: str):
    st.header("Claims Export")
    fmt = st.radio("Format", ["json", "csv", "xlsx"], horizontal=True)

    if st.button("Generate export"):
        if fmt == "json":
            data = api("get", f"/export/claims?trip_id={trip_id}&fmt=json")
            if data:
                st.write(f"**{data['total']} rows**")
                st.dataframe(pd.DataFrame(data["rows"]), use_container_width=True)
        else:
            resp = requests.get(f"{API_BASE}/export/claims?trip_id={trip_id}&fmt={fmt}")
            if resp.status_code == 200:
                mime = "text/csv" if fmt == "csv" else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                st.download_button(
                    label=f"Download claims.{fmt}",
                    data=resp.content,
                    file_name=f"claims_{trip_id}.{fmt}",
                    mime=mime,
                )
            else:
                st.error(f"Export failed: {resp.status_code}")


# ─── Page: Audit ──────────────────────────────────────────────────────────── #

def page_audit():
    st.header("Audit — Hash Chain Integrity")
    st.write(
        "Walks every record in the audit chain in sequence order "
        "and re-derives each hash. A broken link means a row was edited after it was written."
    )
    if st.button("Run audit check"):
        result = api("get", "/audit/verify")
        if result:
            if result["ok"]:
                st.success(f"✅ Chain intact — {result['total']} records verified.")
            else:
                st.error(
                    f"❌ Chain broken at sequence #{result['broken_at_seq']} "
                    f"(out of {result['total']} records). "
                    "A record was modified after it was written."
                )


# ─── Sidebar + main ───────────────────────────────────────────────────────── #

def main():
    st.set_page_config(
        page_title="Pratibimb — Coordinator Dashboard",
        page_icon="🪞",
        layout="wide",
    )
    st.title("🪞 Pratibimb")
    st.caption("Every screenshot gets an owner, a trail and an honest label.")

    with st.sidebar:
        st.header("Trip")
        trip_id = st.text_input("Trip ID", value=st.session_state.get("trip_id", ""))
        if trip_id:
            st.session_state["trip_id"] = trip_id

        st.divider()
        st.subheader("Create new trip")
        with st.form("create_trip"):
            trip_name = st.text_input("Trip name")
            coord_id = st.text_input("Your coordinator ID")
            create = st.form_submit_button("Create")
        if create and trip_name and coord_id:
            result = api("post", "/trips", json={"name": trip_name, "coordinator_id": coord_id})
            if result:
                st.session_state["trip_id"] = result["trip_id"]
                st.success(f"Created! ID: `{result['trip_id']}`\nJoin code: `{result['join_code']}`")

        st.divider()
        page = st.radio(
            "View",
            ["Roster", "Inbox", "Trail", "Decisions", "Export", "Audit"],
        )

    tid = st.session_state.get("trip_id", "")

    if page == "Roster":
        if not tid:
            st.warning("Enter or create a Trip ID in the sidebar first.")
        else:
            page_roster(tid)
    elif page == "Inbox":
        if not tid:
            st.warning("Enter a Trip ID in the sidebar first.")
        else:
            page_inbox(tid)
    elif page == "Trail":
        page_trail()
    elif page == "Decisions":
        page_decisions()
    elif page == "Export":
        if not tid:
            st.warning("Enter a Trip ID in the sidebar first.")
        else:
            page_export(tid)
    elif page == "Audit":
        page_audit()


if __name__ == "__main__":
    main()
