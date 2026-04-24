"""
pages/2_Draft_Board.py
----------------------
Live draft board. Shows drafted players in search with indicator.
Scarcity recalculates after every pick.
"""

import streamlit as st
import pandas as pd
from engine.draft_state import DraftState
from engine.vorp import get_scarcity_scores, get_baseline_counts

st.set_page_config(page_title="Draft Board", page_icon="📋", layout="wide")
st.title("📋 Draft Board")

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
h1.metric("Round",         ds.current_round)
h2.metric("Pick #",        ds.current_pick_number)
h3.metric("On the Clock",  "🟢 YOU" if ds.is_user_turn else f"Team {ds.current_team}")
h4.metric("Your Position", f"#{cfg['draft_position']}")

if ds.draft_complete:
    st.success("🎉 Draft Complete!")

st.divider()

left_col, right_col = st.columns([3, 2])

# ─── LEFT: Player board ───────────────────────────────────────────────────────
with left_col:
    st.subheader("Player Board")

    fc1, fc2, fc3 = st.columns(3)
    pos_filter       = fc1.selectbox("Position", ["All", "QB", "RB", "WR", "TE", "K", "DST"])
    sort_by          = fc2.selectbox("Sort by", ["VOR", "Projected Pts", "ADP"])
    search_name      = fc3.text_input("Search player", "")
    show_drafted     = st.checkbox("Show drafted players", value=False,
                                   help="Drafted players appear grayed out with a ✓")

    # Pull full board or available only
    if show_drafted or search_name:
        board = ds.all_players_with_status.copy()
    else:
        board = ds.available_players.copy()
        board["drafted"] = False

    # Filters
    if pos_filter != "All":
        board = board[board["position"] == pos_filter]
    if search_name:
        board = board[board["name"].str.contains(search_name, case=False, na=False)]

    sort_col = {"VOR": "vor", "Projected Pts": "projected_points", "ADP": "adp"}[sort_by]
    board    = board.sort_values(sort_col, ascending=(sort_by == "ADP"))

    # Format display — mark drafted players
    def format_name(row):
        return f"✓ {row['name']}" if row.get("drafted", False) else row["name"]

    display = board.copy().head(120)
    display["Name"]      = display.apply(format_name, axis=1)
    display["Proj Pts"]  = display["projected_points"].round(1)
    display["VOR"]       = display["vor"].round(1)
    display["ADP"]       = display["adp"].round(1)
    display["Status"]    = display["drafted"].apply(lambda d: "Drafted" if d else "Available")

    show_cols = ["Name", "position", "team", "Proj Pts", "VOR", "ADP", "Status"]
    display   = display[show_cols].reset_index(drop=True)
    display.columns = ["Name", "Pos", "Team", "Proj Pts", "VOR", "ADP", "Status"]

    selected = st.dataframe(
        display,
        use_container_width=True,
        hide_index=True,
        selection_mode="single-row",
        on_select="rerun",
        height=380,
    )

    selected_rows = selected.selection.rows if selected.selection else []
    if selected_rows:
        raw_selected = board.iloc[selected_rows[0]]
        # Don't allow picking already-drafted players
        if raw_selected.get("drafted", False):
            st.warning(f"**{raw_selected['name']}** has already been drafted.")
            selected_player = None
        else:
            selected_player = raw_selected
            st.info(f"Selected: **{selected_player['name']}** ({selected_player['position']} – {selected_player['team']})")
    else:
        selected_player = None

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

# ─── RIGHT: Recommendations + Scarcity + Roster ───────────────────────────────
with right_col:

    if ds.is_user_turn and not ds.draft_complete:
        st.subheader("💡 Recommendations")
        run_risk = ds.get_run_risk()

        # Position risk bar
        risk_cols = st.columns(4)
        for i, pos in enumerate(["QB", "RB", "WR", "TE"]):
            risk = run_risk.get(pos, {}).get("risk_level", "low")
            icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}[risk]
            risk_cols[i].caption(f"{icon} **{pos}**")
        st.caption("🔴 High demand · 🟡 Moderate · 🟢 Safe to wait")
        st.write("")

        recs = ds.get_recommendations(top_n=5)
        if recs:
            for rec in recs:
                urgency = rec.get("urgency", "low")
                flag    = {"high": "🔴", "medium": "🟡", "low": ""}.get(urgency, "")
                with st.container(border=True):
                    c1, c2 = st.columns([3, 1])
                    c1.markdown(f"{flag} **{rec['name']}** — {rec['position']} ({rec['team']})")
                    c2.metric("VOR", f"{rec['vor']:.1f}")
                    c1.caption(f"Proj: {rec['projected_points']:.1f} pts · ADP: {rec['adp']:.1f}")
                    st.caption(f"_{rec['reasoning']}_")
        else:
            st.caption("No recommendations available.")

    # ── Live scarcity (recalculates from available players) ───────────────────
    st.subheader("📊 Position Scarcity")
    baseline_counts = get_baseline_counts(cfg)
    avail_df        = ds.available_players          # always undrafted only
    scarcity        = get_scarcity_scores(avail_df, baseline_counts)

    sc_cols = st.columns(3)
    for i, (pos, score) in enumerate(scarcity.items()):
        icon = "🔴" if score < 0.3 else "🟡" if score < 0.6 else "🟢"
        sc_cols[i % 3].metric(
            label=f"{icon} {pos}",
            value=f"{score:.0%}",
            help=f"{int(score * baseline_counts.get(pos, 1))} of ~{baseline_counts.get(pos, '?')} starters left"
        )

    # ── My roster ─────────────────────────────────────────────────────────────
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
    pos_list  = ["QB", "RB", "WR", "TE", "K", "DST"]

    header_cols = st.columns([1] + [1] * len(pos_list))
    header_cols[0].markdown("**Team**")
    for i, pos in enumerate(pos_list):
        header_cols[i + 1].markdown(f"**{pos}**")

    for team_num in range(1, cfg["num_teams"] + 1):
        pos_counts = summaries[team_num]["pos_counts"]
        is_user    = team_num == cfg["draft_position"]
        label      = f"Team {team_num}" + (" 👈 YOU" if is_user else "")
        row_cols   = st.columns([1] + [1] * len(pos_list))
        row_cols[0].markdown(f"{'**' + label + '**' if is_user else label}")
        for i, pos in enumerate(pos_list):
            count = pos_counts.get(pos, 0)
            row_cols[i + 1].markdown(f"{'**' + str(count) + '**' if is_user else str(count)}")

    st.write("")
    tab_labels = [f"{'★ ' if t == cfg['draft_position'] else ''}Team {t}"
                  for t in range(1, cfg["num_teams"] + 1)]
    tabs = st.tabs(tab_labels)
    for i, team_num in enumerate(range(1, cfg["num_teams"] + 1)):
        with tabs[i]:
            picks = summaries[team_num]["picks"]
            if picks:
                df = pd.DataFrame(picks)[["round", "player_name", "position"]]
                df.columns = ["Rd", "Player", "Pos"]
                st.dataframe(df, use_container_width=True, hide_index=True)
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

st.divider()
if st.button("🔄 Reset Draft", type="secondary"):
    ds.reset()
    st.rerun()
