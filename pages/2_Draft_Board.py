"""
pages/2_Draft_Board.py
----------------------
Live draft interface with opponent-aware recommendations
and full team composition panel.
"""

import streamlit as st
import pandas as pd
from engine.draft_state import DraftState
from engine.vorp import get_scarcity_scores, get_baseline_counts

st.set_page_config(page_title="Draft Board", page_icon="📋", layout="wide")
st.title("📋 Draft Board")

# ── Guard ─────────────────────────────────────────────────────────────────────
if not st.session_state.get("league_config") or st.session_state.get("players_df") is None:
    st.warning("Complete **League Setup** before starting the draft.")
    st.stop()

cfg = st.session_state.league_config

if st.session_state.draft_state is None:
    st.session_state.draft_state = DraftState(
        players_df=st.session_state.players_df,
        league_config=cfg,
    )
    st.session_state.draft_started = True

ds = st.session_state.draft_state

# ── Header ────────────────────────────────────────────────────────────────────
h1, h2, h3, h4 = st.columns(4)
h1.metric("Round",        ds.current_round)
h2.metric("Pick #",       ds.current_pick_number)
h3.metric("On the Clock", "🟢 YOU" if ds.is_user_turn else f"Team {ds.current_team}")
h4.metric("Your Position", f"#{cfg['draft_position']}")

if ds.draft_complete:
    st.success("🎉 Draft Complete!")

st.divider()

# ── Main layout ───────────────────────────────────────────────────────────────
left_col, right_col = st.columns([3, 2])

# ─── LEFT: Available players ──────────────────────────────────────────────────
with left_col:
    st.subheader("Available Players")

    fc1, fc2, fc3 = st.columns(3)
    pos_filter  = fc1.selectbox("Position", ["All", "QB", "RB", "WR", "TE", "K", "DST"])
    sort_by     = fc2.selectbox("Sort by", ["VOR", "Projected Pts", "ADP"])
    search_name = fc3.text_input("Search", "")

    available = ds.available_players.copy()
    if pos_filter != "All":
        available = available[available["position"] == pos_filter]
    if search_name:
        available = available[available["name"].str.contains(search_name, case=False, na=False)]

    sort_col = {"VOR": "vor", "Projected Pts": "projected_points", "ADP": "adp"}[sort_by]
    available = available.sort_values(sort_col, ascending=(sort_by == "ADP"))

    display = available[["name", "position", "team", "projected_points", "vor", "adp"]].head(100).reset_index(drop=True)
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
        st.info(f"Selected: **{selected_player['name']}** ({selected_player['position']} – {selected_player['team']})")

    b1, b2, b3 = st.columns(3)
    with b1:
        if st.button("✅ My Pick", type="primary",
                     disabled=(not ds.is_user_turn or selected_player is None or ds.draft_complete)):
            ds.make_pick(selected_player["player_id"])
            st.rerun()
    with b2:
        if st.button("👥 Mark as Drafted",
                     disabled=(ds.is_user_turn or selected_player is None or ds.draft_complete)):
            ds.make_pick(selected_player["player_id"])
            st.rerun()
    with b3:
        if st.button("↩️ Undo Last Pick", disabled=not ds.can_undo):
            undone = ds.undo()
            if undone:
                st.toast(f"Undid: {undone['player_name']}")
            st.rerun()

# ─── RIGHT: Recommendations + My Roster ──────────────────────────────────────
with right_col:

    # ── Recommendations ───────────────────────────────────────────────────────
    if ds.is_user_turn and not ds.draft_complete:
        st.subheader("💡 Recommendations")

        run_risk = ds.get_run_risk()

        # Position risk summary bar
        risk_cols = st.columns(len(["QB","RB","WR","TE"]))
        for i, pos in enumerate(["QB", "RB", "WR", "TE"]):
            risk = run_risk.get(pos, {}).get("risk_level", "low")
            icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}[risk]
            risk_cols[i].caption(f"{icon} **{pos}**")

        st.caption("🔴 High demand · 🟡 Moderate · 🟢 Low demand ahead")
        st.write("")

        recs = ds.get_recommendations(top_n=5)
        for rec in recs:
            urgency = rec.get("urgency", "low")
            border_color = {"high": "🔴", "medium": "🟡", "low": ""}.get(urgency, "")
            with st.container(border=True):
                c1, c2 = st.columns([3, 1])
                c1.markdown(f"{border_color} **{rec['name']}** — {rec['position']} ({rec['team']})")
                c2.metric("VOR", f"{rec['vor']:.1f}")
                c1.caption(f"Proj: {rec['projected_points']:.1f} pts · ADP: {rec['adp']:.1f}")
                st.caption(f"_{rec['reasoning']}_")

    # ── Scarcity ──────────────────────────────────────────────────────────────
    st.subheader("📊 Position Scarcity")
    baseline_counts = get_baseline_counts(cfg)
    avail_df = ds.available_players
    if "vor" in avail_df.columns:
        scarcity = get_scarcity_scores(avail_df, baseline_counts)
        sc_cols  = st.columns(3)
        for i, (pos, score) in enumerate(scarcity.items()):
            icon = "🔴" if score < 0.3 else "🟡" if score < 0.6 else "🟢"
            sc_cols[i % 3].caption(f"{icon} **{pos}**: {score:.0%} left")

    # ── My Roster ─────────────────────────────────────────────────────────────
    st.subheader(f"My Roster (Team {cfg['draft_position']})")
    my_picks = ds.rosters.get(cfg["draft_position"], [])
    if my_picks:
        roster_df = pd.DataFrame(my_picks)[["round", "player_name", "position"]]
        roster_df.columns = ["Rd", "Player", "Pos"]
        st.dataframe(roster_df, use_container_width=True, hide_index=True)
    else:
        st.caption("No picks yet.")

# ── All Team Compositions ─────────────────────────────────────────────────────
st.divider()
with st.expander("👥 All Team Compositions", expanded=False):
    summaries = ds.get_all_team_summaries()
    num_teams = cfg["num_teams"]

    # Show position count grid
    pos_list = ["QB", "RB", "WR", "TE", "K", "DST"]
    header_cols = st.columns([1] + [1] * len(pos_list))
    header_cols[0].markdown("**Team**")
    for i, pos in enumerate(pos_list):
        header_cols[i + 1].markdown(f"**{pos}**")

    for team_num in range(1, num_teams + 1):
        summary    = summaries[team_num]
        pos_counts = summary["pos_counts"]
        is_user    = team_num == cfg["draft_position"]
        label      = f"Team {team_num}" + (" 👈 YOU" if is_user else "")

        row_cols = st.columns([1] + [1] * len(pos_list))
        row_cols[0].markdown(f"{'**' + label + '**' if is_user else label}")
        for i, pos in enumerate(pos_list):
            count = pos_counts.get(pos, 0)
            row_cols[i + 1].markdown(f"{'**' + str(count) + '**' if is_user else str(count)}")

    st.write("")

    # Full roster detail per team in tabs
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

# ── Pick log + Reset ──────────────────────────────────────────────────────────
with st.expander("📜 Full Pick Log", expanded=False):
    if ds.drafted_players:
        log_df = pd.DataFrame(ds.drafted_players)
        log_df = log_df[["pick_number", "round", "team", "player_name", "position"]]
        log_df.columns = ["Pick #", "Round", "Team", "Player", "Pos"]
        st.dataframe(log_df, use_container_width=True, hide_index=True)
    else:
        st.caption("No picks yet.")

st.divider()
if st.button("🔄 Reset Draft", type="secondary"):
    ds.reset()
    st.rerun()
