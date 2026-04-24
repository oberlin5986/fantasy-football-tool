"""
pages/3_Simulator.py
--------------------
Practice draft simulator. User drafts their own picks while CPU
fills all other teams using ADP + roster need + variance.
"""

import streamlit as st
import pandas as pd
from engine.draft_state import DraftState

st.set_page_config(page_title="Draft Simulator", page_icon="🎲", layout="wide")
st.title("🎲 Draft Simulator")
st.markdown("Practice your draft strategy before the real thing. CPU teams draft based on ADP.")

# ── Guard ─────────────────────────────────────────────────────────────────────
if not st.session_state.get("league_config") or st.session_state.get("players_df") is None:
    st.warning("⚠️ Complete **League Setup** first.")
    st.stop()

cfg = st.session_state.league_config

# ── Simulator config ──────────────────────────────────────────────────────────
st.subheader("Simulation Settings")

sc1, sc2, sc3 = st.columns(3)
variance     = sc1.selectbox("CPU Variance", ["low", "medium", "high"], index=1,
                              help="How closely CPU teams follow ADP")
auto_advance = sc2.checkbox("Auto-advance CPU picks", value=True,
                             help="Automatically simulate CPU picks without clicking")
show_cpu_picks = sc3.checkbox("Show CPU pick details", value=False)

st.divider()

# ── Initialize sim state (separate from live draft state) ────────────────────
if "sim_state" not in st.session_state or st.session_state.sim_state is None:
    st.session_state.sim_state = None

def start_sim():
    st.session_state.sim_state = DraftState(
        players_df=st.session_state.players_df,
        league_config=cfg,
    )

if st.session_state.sim_state is None:
    if st.button("▶️ Start Simulation", type="primary", use_container_width=True):
        start_sim()
        st.rerun()
    st.stop()

sim = st.session_state.sim_state

# ── Auto-advance CPU picks ────────────────────────────────────────────────────
if auto_advance and not sim.is_user_turn and not sim.draft_complete:
    pick = sim.simulate_pick(variance=variance)
    if show_cpu_picks:
        st.toast(f"Team {pick['team']} drafted {pick['player_name']} ({pick['position']})")
    st.rerun()

# ── Header ────────────────────────────────────────────────────────────────────
h1, h2, h3 = st.columns(3)
h1.metric("Round", sim.current_round)
h2.metric("Pick #", sim.current_pick_number)
h3.metric("Status", "🟢 YOUR PICK" if sim.is_user_turn else f"CPU – Team {sim.current_team}")

if sim.draft_complete:
    st.success("🎉 Simulation complete!")

st.divider()

# ── Main layout ───────────────────────────────────────────────────────────────
left_col, right_col = st.columns([3, 2])

with left_col:
    st.subheader("Available Players")

    pos_filter = st.selectbox("Filter by position", ["All", "QB", "RB", "WR", "TE", "K", "DST"])
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
        height=380,
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
        if st.button("⏩ Simulate Next CPU Pick", disabled=(sim.is_user_turn or sim.draft_complete)):
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
        recs = sim.get_recommendations(top_n=5)
        for _, row in recs.iterrows():
            with st.container(border=True):
                st.markdown(f"**{row['name']}** — {row['position']} ({row['team']})")
                st.caption(f"VOR: {row['vor']:.1f} | Proj: {row['projected_points']:.1f} pts | ADP: {row['adp']:.1f}")

    # My roster
    st.subheader("My Roster")
    my_picks = sim.rosters.get(cfg["draft_position"], [])
    if my_picks:
        roster_df = pd.DataFrame(my_picks)[["round", "player_name", "position"]]
        roster_df.columns = ["Rd", "Player", "Pos"]
        st.dataframe(roster_df, use_container_width=True, hide_index=True)
    else:
        st.caption("No picks yet.")

    # Simulate rest of draft
    if not sim.draft_complete:
        if st.button("⚡ Simulate Remaining Draft", use_container_width=True):
            while not sim.draft_complete:
                if sim.is_user_turn:
                    # Auto-pick best available for user too
                    recs = sim.get_recommendations(top_n=1)
                    if not recs.empty:
                        sim.make_pick(recs.iloc[0].name)  # index = player_id
                else:
                    sim.simulate_pick(variance=variance)
            st.rerun()

# ── Reset ─────────────────────────────────────────────────────────────────────
st.divider()
col_r1, col_r2 = st.columns(2)
with col_r1:
    if st.button("🔄 Reset Simulation", use_container_width=True):
        st.session_state.sim_state = None
        st.rerun()
with col_r2:
    if st.button("💾 Save This Simulation Result", use_container_width=True, disabled=not sim.draft_complete):
        result = {
            "roster": sim.rosters.get(cfg["draft_position"], []),
            "pick_log": sim.drafted_players,
        }
        st.session_state.sim_results.append(result)
        st.success(f"Saved! You now have {len(st.session_state.sim_results)} simulation result(s).")
