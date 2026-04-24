"""
pages/2_Draft_Board.py
----------------------
The live draft interface. Shows available players, user's roster,
pick recommendations, and handles pick / undo actions.
"""

import streamlit as st
import pandas as pd
from engine.draft_state import DraftState
from engine.vorp import get_scarcity_scores, get_baseline_counts

st.set_page_config(page_title="Draft Board", page_icon="📋", layout="wide")
st.title("📋 Draft Board")

# ── Guard: require league setup ───────────────────────────────────────────────
if not st.session_state.get("league_config") or st.session_state.get("players_df") is None:
    st.warning("⚠️ Please complete **League Setup** before starting the draft.")
    st.stop()

cfg = st.session_state.league_config

# ── Initialize draft state ────────────────────────────────────────────────────
if st.session_state.draft_state is None:
    st.session_state.draft_state = DraftState(
        players_df=st.session_state.players_df,
        league_config=cfg,
    )
    st.session_state.draft_started = True

ds = st.session_state.draft_state

# ── Header bar ────────────────────────────────────────────────────────────────
h1, h2, h3, h4 = st.columns(4)
h1.metric("Round",        ds.current_round)
h2.metric("Pick #",       ds.current_pick_number)
h3.metric("On the Clock", f"Team {ds.current_team}" if not ds.is_user_turn else "🟢 YOU")
h4.metric("Your Position", f"#{cfg['draft_position']}")

if ds.draft_complete:
    st.success("🎉 Draft Complete! Check your roster below.")

st.divider()

# ── Main two-column layout ────────────────────────────────────────────────────
left_col, right_col = st.columns([3, 2])

# ─── LEFT: Available players ──────────────────────────────────────────────────
with left_col:
    st.subheader("Available Players")

    # Filters
    fc1, fc2, fc3 = st.columns(3)
    pos_filter  = fc1.selectbox("Position", ["All", "QB", "RB", "WR", "TE", "K", "DST"])
    sort_by     = fc2.selectbox("Sort by", ["VOR", "Projected Pts", "ADP"])
    search_name = fc3.text_input("Search player", "")

    available = ds.available_players.copy()

    if pos_filter != "All":
        available = available[available["position"] == pos_filter]
    if search_name:
        available = available[available["name"].str.contains(search_name, case=False, na=False)]

    sort_col_map = {"VOR": "vor", "Projected Pts": "projected_points", "ADP": "adp"}
    sort_col     = sort_col_map[sort_by]
    available    = available.sort_values(sort_col, ascending=(sort_by == "ADP"))

    # Display table
    display_cols = ["name", "position", "team", "projected_points", "vor", "adp"]
    available_display = available[display_cols].head(100).reset_index(drop=True)
    available_display.columns = ["Name", "Pos", "Team", "Proj Pts", "VOR", "ADP"]

    selected = st.dataframe(
        available_display,
        use_container_width=True,
        hide_index=True,
        selection_mode="single-row",
        on_select="rerun",
        height=420,
    )

    # Pick buttons
    b1, b2, b3 = st.columns(3)

    selected_rows = selected.selection.rows if selected.selection else []
    selected_player = available.iloc[selected_rows[0]] if selected_rows else None

    if selected_player is not None:
        st.info(f"Selected: **{selected_player['name']}** ({selected_player['position']} – {selected_player['team']})")

    with b1:
        if st.button("✅ My Pick", type="primary", disabled=(not ds.is_user_turn or selected_player is None)):
            if selected_player is not None:
                ds.make_pick(selected_player["player_id"])
                st.rerun()

    with b2:
        if st.button("👥 CPU Pick (Mark Drafted)", disabled=(ds.is_user_turn or selected_player is None)):
            if selected_player is not None:
                ds.make_pick(selected_player["player_id"])
                st.rerun()

    with b3:
        if st.button("↩️ Undo Last Pick", disabled=not ds.can_undo):
            undone = ds.undo()
            if undone:
                st.toast(f"Undid pick: {undone['player_name']}")
            st.rerun()

# ─── RIGHT: Roster + Recommendations ─────────────────────────────────────────
with right_col:

    # Recommendations (only show when it's user's turn)
    if ds.is_user_turn and not ds.draft_complete:
        st.subheader("💡 Recommendations")
        recs = ds.get_recommendations(top_n=5)
        for _, row in recs.iterrows():
            with st.container(border=True):
                rc1, rc2 = st.columns([3, 1])
                rc1.markdown(f"**{row['name']}** — {row['position']} ({row['team']})")
                rc2.metric("VOR", f"{row['vor']:.1f}")
                rc1.caption(f"Proj: {row['projected_points']:.1f} pts | ADP: {row['adp']:.1f}")

    # Scarcity alerts
    st.subheader("📊 Position Scarcity")
    baseline_counts = get_baseline_counts(cfg)
    avail_df = ds.available_players
    if "vor" in avail_df.columns:
        scarcity = get_scarcity_scores(avail_df, baseline_counts)
        for pos, score in scarcity.items():
            color = "🔴" if score < 0.3 else "🟡" if score < 0.6 else "🟢"
            st.caption(f"{color} **{pos}**: {score:.0%} of starters remaining")

    # User's roster
    st.subheader(f"My Roster (Team {cfg['draft_position']})")
    my_picks = ds.rosters.get(cfg["draft_position"], [])
    if my_picks:
        roster_df = pd.DataFrame(my_picks)[["round", "player_name", "position"]]
        roster_df.columns = ["Rd", "Player", "Pos"]
        st.dataframe(roster_df, use_container_width=True, hide_index=True)
    else:
        st.caption("No picks yet.")

# ── Pick log ──────────────────────────────────────────────────────────────────
with st.expander("📜 Full Pick Log", expanded=False):
    if ds.drafted_players:
        log_df = pd.DataFrame(ds.drafted_players)
        log_df = log_df[["pick_number", "round", "team", "player_name", "position"]]
        log_df.columns = ["Pick #", "Round", "Team", "Player", "Pos"]
        st.dataframe(log_df, use_container_width=True, hide_index=True)
    else:
        st.caption("No picks yet.")

# ── Reset draft ───────────────────────────────────────────────────────────────
st.divider()
if st.button("🔄 Reset Draft", type="secondary"):
    ds.reset()
    st.rerun()
