"""
Pratibimb coordinator dashboard — Streamlit app.

Pages (via sidebar navigation):
  🏠 Overview   — trip metrics at a glance
  👥 Roster     — all travellers + join code
  📥 Inbox      — exceptions only, with reasons
  🔍 Trail      — full evidence history for one item
  ✅ Decisions  — approve / reject / request proof
  📤 Export     — download CSV or XLSX
  🔒 Audit      — hash-chain integrity check

Run:
    python -m streamlit run dashboard/app.py
"""
from __future__ import annotations

import time
from typing import Optional

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st

API_BASE = st.secrets.get("api", {}).get("base_url", "http://localhost:8000")
REFRESH_INTERVAL = 30   # seconds for auto-refresh on live pages


# ─── Braille terrain background ───────────────────────────────────────────── #
def _inject_braille_background():
    """
    Injects the BrailleTerrainBackground canvas animation into the Streamlit
    page as a fixed full-screen backdrop. Ported from BrailleTerrainBackground.tsx.
    """
    import streamlit.components.v1 as components
    components.html("""
<style>
  #braille-bg {
    position: fixed;
    inset: 0;
    width: 100vw;
    height: 100vh;
    z-index: 0;
    pointer-events: none;
    background: #0a0b0d;
  }
  #braille-bg canvas {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    filter: blur(2px);
  }
</style>
<div id="braille-bg"><canvas id="braille-canvas" aria-hidden="true"></canvas></div>
<script>
(function () {
  const DOT_BITS  = [0x01, 0x02, 0x04, 0x40, 0x08, 0x10, 0x20, 0x80];
  const DOT_ORDER = [0.06, 0.56, 0.31, 0.81, 0.43, 0.93, 0.18, 0.68];
  const COLOR      = "#c3cad4";
  const CELL_SIZE  = 10;
  const SCALE      = 0.06;
  const SPEED      = 1;
  const OPACITY    = 0.85;
  const TIERS      = [{min:0.1,alpha:0.3},{min:0.4,alpha:0.62},{min:0.66,alpha:1}];

  function field(x, y, t) {
    return (
      Math.sin(0.9*x + 0.25*t) * Math.cos(0.7*y - 0.18*t) * 0.5 +
      0.3 * Math.sin(1.7*x - 1.1*y + 0.22*t) +
      Math.sin(0.35*x + 0.3*t) * Math.cos(0.45*y + 0.2*t) * 0.55 +
      0.2 * Math.sin(3.1*x + 0.12*t) * Math.cos(2.7*y - 0.1*t)
    );
  }

  const canvas = document.getElementById("braille-canvas");
  const ctx    = canvas.getContext("2d", {alpha: true});
  const cw = CELL_SIZE, ch = cw * 1.6;
  const zoom = SCALE, rate = SPEED;
  let width = 0, height = 0, elapsed = 0, previous = 0, frame = 0, fn = 0;
  const buckets = TIERS.map(() => []);

  function draw() {
    ctx.clearRect(0, 0, width, height);
    ctx.font = `400 ${cw*1.25}px ui-monospace,monospace`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    buckets.forEach(b => b.length = 0);
    const cols = Math.ceil(width / cw) + 1;
    const rows = Math.ceil(height / ch) + 1;
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        let bits = 0, sum = 0;
        for (let d = 0; d < 8; d++) {
          const sx = c + (d < 4 ? 0.25 : 0.75);
          const sy = r + ((d % 4) + 0.5) / 4;
          const raw = (field(sx*zoom*2, sy*zoom*2*1.6, elapsed) + 1.55) / 3.1;
          const v = raw < 0.5 ? 2*raw*raw : 1 - 2*(1-raw)*(1-raw);
          sum += v;
          if (v > DOT_ORDER[d]) bits |= DOT_BITS[d];
        }
        if (!bits) bits = 0x02;
        const mean = sum / 8;
        for (let i = TIERS.length - 1; i >= 0; i--) {
          if (mean >= TIERS[i].min) {
            buckets[i].push(String.fromCharCode(0x2800 + bits), c*cw + cw/2, r*ch + ch/2);
            break;
          }
        }
      }
    }
    buckets.forEach((bucket, i) => {
      ctx.globalAlpha = OPACITY * TIERS[i].alpha;
      ctx.fillStyle = COLOR;
      for (let j = 0; j < bucket.length; j += 3)
        ctx.fillText(bucket[j], bucket[j+1], bucket[j+2]);
    });
    ctx.globalAlpha = 1;
  }

  function resize() {
    const dpr = Math.min(devicePixelRatio || 1, 2);
    width  = window.innerWidth;
    height = window.innerHeight;
    canvas.width  = Math.max(1, Math.floor(width  * dpr));
    canvas.height = Math.max(1, Math.floor(height * dpr));
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    draw();
  }

  function tick(now) {
    elapsed += Math.min((now - previous) / 1000, 0.1) * rate;
    previous = now;
    if (++fn % 2 === 0) draw();
    frame = requestAnimationFrame(tick);
  }

  window.addEventListener("resize", resize);
  resize();
  previous = performance.now();
  frame = requestAnimationFrame(tick);
})();
</script>
""", height=0)  # height=0 — the canvas is fixed-position, takes no layout space

# ─── Coordinator login gate ───────────────────────────────────────────────── #
def _login_wall():
    """Simple coordinator login — just an ID + trip ID pair. No password server needed."""
    if st.session_state.get("logged_in"):
        return True

    st.markdown("## 🪞 Pratibimb")
    st.markdown("#### Coordinator Login")
    st.caption("Enter your coordinator ID and your trip ID to access your dashboard.")
    st.divider()

    with st.form("login"):
        coord = st.text_input("Coordinator ID", placeholder="e.g. coord-vansh")
        trip  = st.text_input("Trip ID", placeholder="Paste the trip ID you received when creating the trip")
        submit = st.form_submit_button("Open dashboard", use_container_width=True, type="primary")

    if submit:
        if not coord.strip() or not trip.strip():
            st.error("Both fields are required.")
            return False
        # Verify trip exists and belongs to this coordinator
        resp = api("get", f"/trips/{trip.strip()}/summary")
        if not resp:
            return False
        if resp.get("coordinator_id") != coord.strip():
            st.error("Coordinator ID does not match this trip. Check both values and try again.")
            return False
        st.session_state["logged_in"]      = True
        st.session_state["coordinator_id"] = coord.strip()
        st.session_state["trip_id"]        = trip.strip()
        st.session_state["trip_name"]      = resp.get("name", "")
        st.rerun()

    st.divider()
    st.markdown("**New coordinator?** Create your trip first via the API or ask your admin.")
    st.code("POST /trips  {name: '...', coordinator_id: '...'}", language="bash")
    return False


# ─── Page config (must be first Streamlit call) ───────────────────────────── #
st.set_page_config(
    page_title="Pratibimb",
    page_icon="🪞",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        "Get Help": None,
        "Report a bug": None,
        "About": "Pratibimb — Every screenshot gets an owner, a trail and an honest label.",
    },
)

# Inject braille terrain background
_inject_braille_background()


# ─── Custom CSS ───────────────────────────────────────────────────────────── #
st.markdown("""
<style>
/* Make Streamlit's own background transparent so braille canvas shows through */
.stApp { background: transparent !important; }
[data-testid="stAppViewContainer"] { background: transparent !important; }
[data-testid="stHeader"] { background: transparent !important; }
[data-testid="stSidebar"] {
    background: rgba(10, 11, 13, 0.82) !important;
    backdrop-filter: blur(12px);
    min-width: 240px; max-width: 280px;
}

/* Metric cards */
[data-testid="stMetric"] {
    background: rgba(26, 26, 46, 0.75);
    border: 1px solid #2D2D4E;
    border-radius: 10px;
    padding: 12px 16px;
    backdrop-filter: blur(8px);
}
[data-testid="stMetricValue"] { font-size: 2rem !important; }

/* Main content area — slightly frosted */
[data-testid="stMainBlockContainer"] {
    background: rgba(10, 11, 13, 0.55) !important;
    backdrop-filter: blur(6px);
    border-radius: 12px;
}

/* Verdict badges */
.badge-green  { background:#1A7A4A; color:#fff; padding:2px 10px; border-radius:12px; font-size:0.8rem; }
.badge-blue   { background:#1B5E9E; color:#fff; padding:2px 10px; border-radius:12px; font-size:0.8rem; }
.badge-orange { background:#C84B00; color:#fff; padding:2px 10px; border-radius:12px; font-size:0.8rem; }
.badge-red    { background:#B71C1C; color:#fff; padding:2px 10px; border-radius:12px; font-size:0.8rem; }

/* Code blocks */
code { font-size: 0.85rem !important; }

/* Expander header */
[data-testid="stExpander"] summary { font-weight: 600; }
</style>
""", unsafe_allow_html=True)


# ─── API helper ───────────────────────────────────────────────────────────── #
def api(method: str, path: str, **kwargs):
    try:
        resp = getattr(requests, method)(f"{API_BASE}{path}", timeout=10, **kwargs)
        if resp.status_code >= 400:
            st.error(f"API {resp.status_code}: {resp.text[:200]}")
            return None
        ct = resp.headers.get("content-type", "")
        return resp.json() if "application/json" in ct else resp
    except requests.exceptions.ConnectionError:
        st.error("Cannot reach API server. Make sure `python main.py --mode api` is running.")
        return None


def _badge(verdict: str) -> str:
    css = {
        "corroborated": "badge-green",
        "extracted":    "badge-blue",
        "needs_review": "badge-orange",
        "unreadable":   "badge-red",
    }
    emoji = {
        "corroborated": "🟢",
        "extracted":    "🔵",
        "needs_review": "🟠",
        "unreadable":   "🔴",
    }
    cls = css.get(verdict, "badge-blue")
    ico = emoji.get(verdict, "⚪")
    return f'<span class="{cls}">{ico} {verdict}</span>'


def _rel_icon(rel_type: Optional[str]) -> str:
    return {"EXACT": "🔗 EXACT", "INFERRED": "〰️ INFERRED",
            "MANUAL": "✋ MANUAL", "UNMATCHED": "❓ UNMATCHED"}.get(rel_type or "", "—")


# ─── Sidebar ──────────────────────────────────────────────────────────────── #
with st.sidebar:
    st.markdown("## 🪞 Pratibimb")
    st.caption("Coordinator Dashboard")
    st.divider()

    # Show logged-in coordinator
    if st.session_state.get("logged_in"):
        st.success(f"👤 {st.session_state.get('coordinator_id','')}")
        st.caption(f"Trip: **{st.session_state.get('trip_name','')}**")
        if st.button("🚪 Log out", use_container_width=True):
            for k in ["logged_in","coordinator_id","trip_id","trip_name","trail_id"]:
                st.session_state.pop(k, None)
            st.rerun()
        st.divider()
    else:
        # Trip selector for first-time / manual entry
        st.markdown("**Active Trip**")
        trip_id_input = st.text_input(
            "Trip ID", value=st.session_state.get("trip_id", ""),
            placeholder="Paste trip ID here", label_visibility="collapsed"
        )
        if trip_id_input:
            st.session_state["trip_id"] = trip_id_input.strip()

    # Quick create (always visible)
    with st.expander("➕ Create new trip"):
        with st.form("create_trip", clear_on_submit=True):
            trip_name = st.text_input("Trip name", placeholder="Namma Metro Offsite")
            coord_id  = st.text_input("Your coordinator ID", placeholder="coord-vansh")
            if st.form_submit_button("Create", use_container_width=True):
                if trip_name and coord_id:
                    r = api("post", "/trips", json={"name": trip_name, "coordinator_id": coord_id})
                    if r:
                        st.session_state["trip_id"]        = r["trip_id"]
                        st.session_state["trip_name"]      = trip_name
                        st.session_state["coordinator_id"] = coord_id
                        st.session_state["logged_in"]      = True
                        st.success(f"Trip ID: `{r['trip_id'][:8]}…`")
                        st.info(f"Join code: **{r['join_code']}**")
                        st.rerun()

    st.divider()

    page = st.radio(
        "Navigate",
        ["🏠 Overview", "👥 Roster", "📥 Inbox", "🔍 Trail", "✅ Decisions", "📤 Export", "🔒 Audit"],
        label_visibility="collapsed",
    )

    st.divider()
    health = api("get", "/health")
    if health and health.get("status") == "ok":
        st.success("API ✅ online", icon="🟢")
    else:
        st.error("API offline", icon="🔴")


# ─── Login gate ───────────────────────────────────────────────────────────── #
if not st.session_state.get("logged_in"):
    if not _login_wall():
        st.stop()   # don't render any page content until logged in


tid = st.session_state.get("trip_id", "")
coord_id_active = st.session_state.get("coordinator_id", "")


# ─── Page: Overview ───────────────────────────────────────────────────────── #
def page_overview():
    st.title("🏠 Overview")
    if not tid:
        st.info("Create or select a trip in the sidebar to get started.")
        st.markdown("""
        **Quick start:**
        1. Expand **➕ Create new trip** in the sidebar
        2. Give it a name and your coordinator ID → click Create
        3. Share the **join code** with your travellers
        4. Travellers send `/join CODE` to the Telegram bot, then forward their screenshots
        """)
        return

    summary = api("get", f"/trips/{tid}/summary")
    if not summary:
        return

    st.markdown(f"### {summary['name']}")
    st.caption(f"Trip ID: `{summary['trip_id']}` · Status: **{summary['status'].upper()}**")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("👥 Travellers",       summary["traveller_count"])
    col2.metric("📸 Screenshots filed", summary["evidence_count"])
    col3.metric("⚠️ Open cases",       summary["open_case_count"],
                delta=f"-{summary['open_case_count']}" if summary["open_case_count"] == 0 else None,
                delta_color="inverse")
    col4.metric("🔑 Join code",        summary.get("join_code") or "—")

    if summary["open_case_count"] > 0:
        st.warning(f"**{summary['open_case_count']} item(s) need your attention.** Go to 📥 Inbox.")

    st.divider()

    # Sparkline: submissions over time (requires evidence data from export)
    exp = api("get", f"/export/claims?trip_id={tid}&fmt=json")
    if exp and exp.get("rows"):
        df = pd.DataFrame(exp["rows"])
        if "received_at" in df.columns:
            df["received_at"] = pd.to_datetime(df["received_at"], errors="coerce")
            df["hour"] = df["received_at"].dt.floor("h")
            counts = df.groupby("hour").size().reset_index(name="count")
            fig = px.bar(counts, x="hour", y="count",
                         title="Submissions over time",
                         color_discrete_sequence=["#7C3AED"])
            fig.update_layout(
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                margin=dict(l=0, r=0, t=40, b=0),
                xaxis_title="", yaxis_title="Screenshots",
            )
            st.plotly_chart(fig, use_container_width=True)

        # Verdict breakdown donut
        if "verdict" in df.columns:
            vc = df["verdict"].value_counts().reset_index()
            vc.columns = ["verdict", "count"]
            fig2 = px.pie(
                vc, names="verdict", values="count", hole=0.55,
                color="verdict",
                color_discrete_map={
                    "corroborated": "#1A7A4A", "extracted": "#1B5E9E",
                    "needs_review": "#C84B00", "unreadable": "#B71C1C",
                },
                title="Evidence levels",
            )
            fig2.update_layout(
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                margin=dict(l=0, r=0, t=40, b=0),
                showlegend=True,
            )
            col_a, col_b = st.columns([1, 1])
            col_a.plotly_chart(fig2, use_container_width=True)

            # Screenshot type breakdown
            if "screenshot_type" in df.columns:
                tc = df["screenshot_type"].value_counts().reset_index()
                tc.columns = ["type", "count"]
                fig3 = px.bar(tc, x="count", y="type", orientation="h",
                              title="Screenshot types",
                              color_discrete_sequence=["#7C3AED"])
                fig3.update_layout(
                    plot_bgcolor="rgba(0,0,0,0)",
                    paper_bgcolor="rgba(0,0,0,0)",
                    margin=dict(l=0, r=0, t=40, b=0),
                    xaxis_title="Count", yaxis_title="",
                )
                col_b.plotly_chart(fig3, use_container_width=True)


# ─── Page: Roster ─────────────────────────────────────────────────────────── #
def page_roster():
    st.title("👥 Roster")
    if not tid:
        st.warning("Select a trip in the sidebar.")
        return

    summary = api("get", f"/trips/{tid}/summary")
    if not summary:
        return

    col1, col2 = st.columns([2, 1])
    with col1:
        st.subheader("Join code")
        st.code(summary.get("join_code") or "—", language=None)
        st.caption("Travellers send `/join CODE` to the Telegram bot.")
    with col2:
        if st.button("🔄 Refresh join code", use_container_width=True):
            r = api("post", f"/trips/{tid}/join-code")
            if r:
                st.success(f"New code: **{r['join_code']}**")
                st.rerun()

    st.divider()
    travellers = summary.get("travellers", [])
    if not travellers:
        st.info("No travellers have joined yet. Share the join code above.")
        return

    df = pd.DataFrame(travellers)
    df = df.rename(columns={
        "display_name": "Name", "sender_id": "Sender ID",
        "language_pref": "Language", "joined_at": "Joined at",
    })
    df["Joined at"] = pd.to_datetime(df["Joined at"], errors="coerce").dt.strftime("%d %b %Y %H:%M")
    st.dataframe(df[["Name","Sender ID","Language","Joined at"]], use_container_width=True, hide_index=True)


# ─── Page: Inbox ──────────────────────────────────────────────────────────── #
def page_inbox():
    st.title("📥 Exceptions Inbox")
    if not tid:
        st.warning("Select a trip in the sidebar.")
        return

    # Auto-refresh toggle
    col_h, col_r = st.columns([4, 1])
    with col_r:
        auto = st.toggle("Auto-refresh", value=False)

    data = api("get", f"/trips/{tid}/inbox")
    if not data:
        return

    exceptions = data.get("exceptions", [])
    total      = data.get("total_items", 0)

    col1, col2 = st.columns(2)
    col1.metric("Total submissions", total)
    col2.metric("Exceptions", len(exceptions),
                delta=len(exceptions) if len(exceptions) > 0 else None,
                delta_color="inverse")

    if not exceptions:
        st.success("✅ All clear — no exceptions.")
        if auto:
            time.sleep(REFRESH_INTERVAL)
            st.rerun()
        return

    st.divider()
    for exc in exceptions:
        verdict = exc["verdict"]
        icon = {"corroborated":"🟢","extracted":"🔵","needs_review":"🟠","unreadable":"🔴"}.get(verdict,"⚪")
        header = (
            f"{icon} **{exc['screenshot_type']}** · "
            f"{exc['received_at'][:16].replace('T',' ')} · "
            f"sender `{exc['sender_id'][:10]}`"
        )
        with st.expander(header, expanded=(verdict == "needs_review")):
            c1, c2, c3 = st.columns(3)
            c1.markdown(f"**Verdict**  \n{_badge(verdict)}", unsafe_allow_html=True)
            c2.markdown(f"**Confidence**  \n`{exc['type_confidence']:.0%}`")
            c3.markdown(f"**Link**  \n`{_rel_icon(exc.get('relationship_type'))}`")

            st.markdown(f"**Evidence level:** `{exc['overall_level']}`")
            if exc["machine_states"]:
                st.markdown("**States:** " + " · ".join(f"`{s}`" for s in exc["machine_states"]))
            st.markdown(f"**Reason:** {exc['reason']}")

            col_a, col_b = st.columns(2)
            if exc.get("needs_challenge"):
                if col_a.button("💬 Send challenge", key=f"ch_{exc['evidence_id']}"):
                    r = api("post", f"/challenge/{exc['evidence_id']}")
                    if r and r.get("challenge_sent"):
                        st.success("Challenge sent to traveller.")
            if col_b.button("🔍 View trail", key=f"trail_{exc['evidence_id']}"):
                st.session_state["trail_id"] = exc["evidence_id"]
                st.info(f"Go to 🔍 Trail page and search for `{exc['evidence_id'][:8]}`")

            st.caption(f"Ref: `{exc['evidence_id']}`")

    if auto:
        time.sleep(REFRESH_INTERVAL)
        st.rerun()


# ─── Page: Trail ──────────────────────────────────────────────────────────── #
def page_trail():
    st.title("🔍 Evidence Trail")

    default = st.session_state.get("trail_id", "")
    evidence_id = st.text_input(
        "Evidence ID", value=default,
        placeholder="Paste full evidence ID (from inbox or reply card ref)"
    ).strip()

    if not evidence_id:
        st.info("Paste an evidence ID above to view its full trail.")
        return

    data = api("get", f"/records/{evidence_id}/trail")
    if not data:
        return

    # Evidence card
    ev = data["evidence"]
    st.subheader("📋 Evidence record")
    cols = st.columns(4)
    cols[0].markdown(f"**Channel**  \n`{ev.get('channel','—')}`")
    cols[1].markdown(f"**Received**  \n`{ev.get('received_at','')[:16].replace('T',' ')}`")
    cols[2].markdown(f"**Status**  \n`{ev.get('status','—')}`")
    cols[3].markdown(f"**SHA-256**  \n`{ev.get('sha256','')[:16]}…`")

    st.divider()

    # Interpretations
    st.subheader("🧠 Interpretations")
    for i, interp in enumerate(data["interpretations"]):
        label = (f"[{i+1}] **{interp['screenshot_type']}** · "
                 f"conf `{interp['type_confidence']:.0%}` · "
                 f"{interp['created_at'][:16].replace('T',' ')}")
        with st.expander(label, expanded=(i == len(data["interpretations"]) - 1)):
            fields = interp.get("fields", {})
            fc     = interp.get("field_confidence", {})
            if fields:
                rows = [
                    {"Field": k, "Value": str(v) if v is not None else "—",
                     "Confidence": f"{fc.get(k, 0):.0%}"}
                    for k, v in fields.items() if v is not None
                ]
                if rows:
                    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            st.caption(f"Model: `{interp.get('model_version','—')}` · Producer: `{interp.get('producer','—')}`")

    st.divider()

    # Relationships
    st.subheader("🔗 Relationships")
    if data["relationships"]:
        rel_df = pd.DataFrame([{
            "Type":       r["type"],
            "Basis":      ", ".join(r["basis"]),
            "Score":      f"{r['score']:.2f}",
            "Reason":     r["plain_reason"],
            "Created by": r["created_by"],
        } for r in data["relationships"]])
        st.dataframe(rel_df, use_container_width=True, hide_index=True)
    else:
        st.info("No relationships recorded yet.")

    st.divider()

    # Decisions
    st.subheader("✅ Decisions")
    if data["decisions"]:
        dec_df = pd.DataFrame([{
            "Action":     d["action"],
            "By":         d["decided_by"],
            "Reason":     d["reason"] or "—",
            "At":         d["created_at"][:16].replace("T"," "),
        } for d in data["decisions"]])
        st.dataframe(dec_df, use_container_width=True, hide_index=True)
    else:
        st.info("No decisions recorded yet.")


# ─── Page: Decisions ──────────────────────────────────────────────────────── #
def page_decisions():
    st.title("✅ Record a Decision")
    st.caption("Every decision is timestamped, signed and hash-chained. It cannot be deleted.")

    with st.form("decision_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        subject_ref = col1.text_input("Evidence ID *", placeholder="Full UUID from trail/inbox")
        decided_by  = col2.text_input("Coordinator ID *",
                                       value=st.session_state.get("coordinator_id", ""),
                                       placeholder="Your ID")
        action = st.selectbox("Action *", [
            "approved", "rejected", "proof_requested", "linked_manually"
        ], format_func=lambda x: {
            "approved":        "✅ Approved — accept this claim",
            "rejected":        "❌ Rejected — dismiss this claim",
            "proof_requested": "🔁 Proof requested — ask for more evidence",
            "linked_manually": "🔗 Link manually — connect to another evidence item",
        }[x])
        reason  = st.text_area("Reason", placeholder="Brief note visible in the audit trail")
        link_to = st.text_input(
            "Link to evidence ID (linked_manually only)",
            placeholder="Leave blank for other actions"
        )
        submitted = st.form_submit_button("Submit decision", use_container_width=True, type="primary")

    if submitted:
        if not subject_ref or not decided_by:
            st.error("Evidence ID and Coordinator ID are required.")
        else:
            payload = {"subject_ref": subject_ref.strip(), "action": action,
                       "decided_by": decided_by.strip(), "reason": reason}
            if action == "linked_manually" and link_to.strip():
                payload["link_to_evidence_id"] = link_to.strip()
            r = api("post", "/decisions", json=payload)
            if r:
                st.success(f"Decision `{r['dec_id'][:12]}…` recorded — **{action}**")


# ─── Page: Export ─────────────────────────────────────────────────────────── #
def page_export():
    st.title("📤 Claims Export")
    if not tid:
        st.warning("Select a trip in the sidebar.")
        return

    fmt = st.radio("Format", ["json", "csv", "xlsx"], horizontal=True,
                   captions=["Preview in browser", "Spreadsheet (comma)", "Excel workbook"])
    st.divider()

    if st.button("Generate", type="primary"):
        if fmt == "json":
            data = api("get", f"/export/claims?trip_id={tid}&fmt=json")
            if data:
                rows = data.get("rows", [])
                st.metric("Rows", len(rows))
                if rows:
                    df = pd.DataFrame(rows)
                    # Highlight verdict column
                    st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            resp = requests.get(f"{API_BASE}/export/claims?trip_id={tid}&fmt={fmt}", timeout=30)
            if resp.status_code == 200:
                mime = ("text/csv" if fmt == "csv"
                        else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                st.download_button(
                    f"⬇️ Download claims.{fmt}",
                    data=resp.content,
                    file_name=f"claims_{tid[:8]}.{fmt}",
                    mime=mime,
                    use_container_width=True,
                    type="primary",
                )
            else:
                st.error(f"Export failed: {resp.status_code}")


# ─── Page: Audit ──────────────────────────────────────────────────────────── #
def page_audit():
    st.title("🔒 Audit — Hash Chain")
    st.markdown(
        "Every record write is chained: `record_hash = SHA-256(record_json + prev_hash)`. "
        "Any row edited after it was written breaks the chain at that exact sequence number."
    )
    st.divider()

    if st.button("▶ Run integrity check", type="primary"):
        with st.spinner("Verifying chain…"):
            r = api("get", "/audit/verify")
        if r:
            if r["ok"]:
                st.success(f"✅ Chain intact — **{r['total']}** records verified.")
                st.balloons()
            else:
                st.error(
                    f"❌ Chain broken at sequence **#{r['broken_at_seq']}** "
                    f"(out of {r['total']} records). "
                    "A row was modified after it was written."
                )

    st.divider()
    st.markdown("#### How it works")
    st.markdown("""
    ```
    record_hash[0] = SHA256(record_json[0] + "000...0")   ← genesis
    record_hash[1] = SHA256(record_json[1] + record_hash[0])
    record_hash[N] = SHA256(record_json[N] + record_hash[N-1])
    ```
    If any record is changed, its hash changes, which breaks every subsequent link.
    The verifier detects this at the first broken link and reports the exact sequence number.
    """)


# ─── Router ───────────────────────────────────────────────────────────────── #
if   page == "🏠 Overview":  page_overview()
elif page == "👥 Roster":    page_roster()
elif page == "📥 Inbox":     page_inbox()
elif page == "🔍 Trail":     page_trail()
elif page == "✅ Decisions": page_decisions()
elif page == "📤 Export":    page_export()
elif page == "🔒 Audit":     page_audit()
