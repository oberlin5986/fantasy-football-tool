"""
pages/3_Simulator.py
--------------------
Practice draft simulator with CPU auto-draft and full team composition view.
"""

import streamlit as st
import pandas as pd
from engine.draft_state import DraftState

st.set_page_config(page_title="Draft Simulator", page_icon="🎲", layout="wide")
st.title("🎲 Draft Simulator")
st.markdown("Practice your strategy. CPU teams draft using ADP + roster need.")

# ── Guard ─────────────────────────────────────────────────────────────────────
if not st.session_state.get("league_config") or st.session_state.get("players_df") is None:
    st.warning("Complete **League Setup** first.")
    st.stop()

cfg = st.session_state.league_config

# ── Sim settings ──────────────────────────────────────────────────────────────
sc1, sc2, sc3 = st.columns(3)
variance       = sc1.selectbox("CPU Variance", ["low", "medium", "high"], index=1)
auto_advance   = sc2.checkbox("Auto-advance CPU picks", value=True)
show_cpu_picks = sc3.checkbox("Show CPU pick toasts", value=False)

st.divider()

# ── Init sim state ────────────────────────────────────────────────────────────
if "sim_state" not in st.session_state or st.session_state.sim_state is None:
    st.session_state.sim_state = None

if st.session_state.sim_state is None:
    if st.button("▶️ Start Simulation", type="primary", use_container_width=True):
        st.session_state.sim_state = DraftState(
            players_df=st.session_state.players_df,
            league_config=cfg,
        )
        st.rerun()
    st.stop()

sim = st.session_state.sim_state

# ── Auto-advance CPU picks ────────────────────────────────────────────────────
if auto_advance and not sim.is_user_turn and not sim.draft_complete:
    pick = sim.simulate_pick(variance=variance)
    if show_cpu_picks:
        st.toast(f"Team {pick['team']}: {pick['player_name']} ({pick['position']})")
    st.rerun()

# ── Turn indicator banner ─────────────────────────────────────────────────────
if sim.draft_complete:
    st.success("🎉 Simulation complete!")
elif sim.is_user_turn:
    st.markdown(
        """
        <div style="background-color:#1a6b3c;padding:14px 20px;border-radius:8px;
                    margin-bottom:8px;border-left:6px solid #2ecc71;">
            <span style="color:white;font-size:1.2rem;font-weight:700;">
                🟢 YOUR PICK — You are on the clock!
            </span>
        </div>
        """,
        unsafe_allow_html=True,
    )
else:
    st.markdown(
        f"""
        <div style="background-color:#2c3e50;padding:14px 20px;border-radius:8px;
                    margin-bottom:8px;border-left:6px solid #7f8c8d;">
            <span style="color:#bdc3c7;font-size:1.1rem;font-weight:600;">
                ⏳ CPU Drafting — Team {sim.current_team} is on the clock
            </span>
        </div>
        """,
        unsafe_allow_html=True,
    )

# ── Header metrics ─────────────────────────────────────────────────────────────
h1, h2, h3 = st.columns(3)
h1.metric("Round",  sim.current_round)
h2.metric("Pick #", sim.current_pick_number)
h3.metric("Status", "🟢 YOUR PICK" if sim.is_user_turn else f"CPU – Team {sim.current_team}")

st.divider()

# ── Main layout ───────────────────────────────────────────────────────────────
left_col, right_col = st.columns([3, 2])

with left_col:
    st.subheader("Available Players")

    pos_filter = st.selectbox("Filter", ["All", "QB", "RB", "WR", "TE", "K", "DST"])
    available  = sim.available_players.copy()
    if pos_filter != "All":
        available = available[available["position"] == pos_filter]
    available = available.sort_values("vor", ascending=False)

    display = available[["name", "position", "team", "projected_points", "vor", "adp"]].head(80)
    display.columns = ["Name", "Pos", "Team", "Proj Pts", "VOR", "ADP"]

    selected = st.dataframe(
        display,
        use_container_width=True,
        hide_index=True,
        selection_mode="single-row",
        on_select="rerun",
        height=360,
    )

    selected_rows   = selected.selection.rows if selected.selection else []
    selected_player = available.iloc[selected_rows[0]] if selected_rows else None

    if selected_player is not None:
        st.info(f"Selected: **{selected_player['name']}** ({selected_player['position']})")

    bc1, bc2, bc3 = st.columns(3)
    with bc1:
        if st.button("✅ Draft Player", type="primary",
                     disabled=(not sim.is_user_turn or selected_player is None or sim.draft_complete)):
            sim.make_pick(selected_player["player_id"])
            st.rerun()
    with bc2:
        if st.button("⏩ Next CPU Pick",
                     disabled=(sim.is_user_turn or sim.draft_complete)):
            sim.simulate_pick(variance=variance)
            st.rerun()
    with bc3:
        if st.button("↩️ Undo", disabled=not sim.can_undo):
            sim.undo()
            st.rerun()

with right_col:
    # Recommendations
    if sim.is_user_turn and not sim.draft_complete:
        st.subheader("💡 Suggested Picks")

        run_risk = sim.get_run_risk()

        risk_cols = st.columns(4)
        for i, pos in enumerate(["QB", "RB", "WR", "TE"]):
            risk = run_risk.get(pos, {}).get("risk_level", "low")
            icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}[risk]
            risk_cols[i].caption(f"{icon} **{pos}**")
        st.caption("🔴 High · 🟡 Medium · 🟢 Low demand ahead")
        st.write("")

        recs = sim.get_recommendations(top_n=5)
        for rec in recs:
            urgency = rec.get("urgency", "low")
            flag    = {"high": "🔴", "medium": "🟡", "low": ""}.get(urgency, "")
            with st.container(border=True):
                c1, c2 = st.columns([3, 1])
                c1.markdown(f"{flag} **{rec['name']}** — {rec['position']} ({rec['team']})")
                c2.metric("VOR", f"{rec['vor']:.1f}")
                c1.caption(f"Proj: {rec['projected_points']:.1f} · ADP: {rec['adp']:.1f}")
                st.caption(f"_{rec['reasoning']}_")

    # My roster
    st.subheader("My Roster")
    my_picks = sim.rosters.get(cfg["draft_position"], [])
    if my_picks:
        roster_df = pd.DataFrame(my_picks)[["round", "player_name", "position"]]
        roster_df.columns = ["Rd", "Player", "Pos"]
        st.dataframe(roster_df, use_container_width=True, hide_index=True)
    else:
        st.caption("No picks yet.")

    # Simulate rest
    if not sim.draft_complete:
        if st.button("⚡ Simulate Rest of Draft", use_container_width=True):
            while not sim.draft_complete:
                if sim.is_user_turn:
                    recs = sim.get_recommendations(top_n=1)
                    if recs:
                        best_id = sim.available_players[
                            sim.available_players["name"] == recs[0]["name"]
                        ]["player_id"].iloc[0]
                        sim.make_pick(best_id)
                else:
                    sim.simulate_pick(variance=variance)
            st.rerun()

# ── All Team Compositions ─────────────────────────────────────────────────────
st.divider()
with st.expander("👥 All Team Compositions", expanded=False):
    summaries = sim.get_all_team_summaries()
    num_teams = cfg["num_teams"]
    pos_list  = ["QB", "RB", "WR", "TE", "K", "DST"]

    # Position count grid
    header_cols = st.columns([1] + [1] * len(pos_list))
    header_cols[0].markdown("**Team**")
    for i, pos in enumerate(pos_list):
        header_cols[i + 1].markdown(f"**{pos}**")

    for team_num in range(1, num_teams + 1):
        pos_counts = summaries[team_num]["pos_counts"]
        is_user    = team_num == cfg["draft_position"]
        label      = f"Team {team_num}" + (" 👈 YOU" if is_user else "")
        row_cols   = st.columns([1] + [1] * len(pos_list))
        row_cols[0].markdown(f"{'**' + label + '**' if is_user else label}")
        for i, pos in enumerate(pos_list):
            count = pos_counts.get(pos, 0)
            row_cols[i + 1].markdown(f"{'**' + str(count) + '**' if is_user else str(count)}")

    st.write("")

    # Tabbed full rosters
    tab_labels = [f"{'★ ' if t == cfg['draft_position'] else ''}Team {t}" for t in range(1, num_teams + 1)]
    tabs = st.tabs(tab_labels)
    for i, team_num in enumerate(range(1, num_teams + 1)):
        with tabs[i]:
            picks = summaries[team_num]["picks"]
            if picks:
                df = pd.DataFrame(picks)[["round", "player_name", "position"]]
                df.columns = ["Rd", "Player", "Pos"]
                st.dataframe(df, use_container_width=True, hide_index=True)
            else:
                st.caption("No picks yet.")

# ── Reset / Save ──────────────────────────────────────────────────────────────
st.divider()
col_r1, col_r2 = st.columns(2)
with col_r1:
    if st.button("🔄 Reset Simulation", use_container_width=True):
        st.session_state.sim_state = None
        st.rerun()
with col_r2:
    if st.button("💾 Save Result", use_container_width=True, disabled=not sim.draft_complete):
        result = {
            "roster":   sim.rosters.get(cfg["draft_position"], []),
            "pick_log": sim.drafted_players,
        }
        st.session_state.sim_results.append(result)
        st.success(f"Saved! {len(st.session_state.sim_results)} simulation(s) stored.")
