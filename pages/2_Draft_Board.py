"""
pages/2_Draft_Board.py
"""

import streamlit as st
import pandas as pd
from engine.draft_state import DraftState
from engine.vorp import get_scarcity_scores, get_baseline_counts
from engine.variance import get_roster_variance_profile

st.set_page_config(page_title="Draft Board", page_icon="📋", layout="wide")
st.title("📋 Draft Board")

# ── Guard ─────────────────────────────────────────────────────────────────────
if not st.session_state.get("league_config") or st.session_state.get("players_df") is None:
    st.warning("Complete **League Setup** before starting the draft.")
    st.stop()

cfg = st.session_state.league_config

# ── Initialize draft state ────────────────────────────────────────────────────
def _init_draft_state():
    try:
        ds = st.session_state.get("draft_state")
        if ds is None:
            raise ValueError("none")
        # Sanity check — if these throw, the object is stale
        _ = ds.current_round
        _ = ds.is_user_turn
        _ = ds.available_players
        return ds
    except Exception:
        pass
    try:
        new_ds = DraftState(
            players_df=st.session_state.players_df,
            league_config=cfg,
        )
        st.session_state.draft_state   = new_ds
        st.session_state.draft_started = True
        return new_ds
    except Exception as e:
        st.error(f"Could not start draft: {e}")
        st.info("Go to **League Setup** and click Save Settings, then return here.")
        st.stop()

ds = _init_draft_state()

# ── Turn banner ───────────────────────────────────────────────────────────────
if ds.draft_complete:
    st.success("🎉 Draft Complete!")
elif ds.is_user_turn:
    st.markdown(
        """<div style="background:#1a6b3c;padding:14px 20px;border-radius:8px;
                       margin-bottom:8px;border-left:6px solid #2ecc71;">
            <span style="color:white;font-size:1.2rem;font-weight:700;">
                🟢 YOUR PICK — You are on the clock!
            </span></div>""",
        unsafe_allow_html=True,
    )
else:
    st.markdown(
        f"""<div style="background:#2c3e50;padding:14px 20px;border-radius:8px;
                        margin-bottom:8px;border-left:6px solid #7f8c8d;">
            <span style="color:#bdc3c7;font-size:1.1rem;font-weight:600;">
                ⏳ Waiting — Team {ds.current_team} is on the clock
            </span></div>""",
        unsafe_allow_html=True,
    )

# ── Header metrics ────────────────────────────────────────────────────────────
h1, h2, h3, h4 = st.columns(4)
h1.metric("Round",         ds.current_round)
h2.metric("Pick #",        ds.current_pick_number)
h3.metric("On the Clock",  "🟢 YOU" if ds.is_user_turn else f"Team {ds.current_team}")
h4.metric("Your Position", f"#{cfg['draft_position']}")

st.divider()

left_col, right_col = st.columns([3, 2])

# ─── LEFT: Player board ───────────────────────────────────────────────────────
with left_col:
    st.subheader("Player Board")

    fc1, fc2, fc3 = st.columns(3)
    pos_filter   = fc1.selectbox("Position", ["All", "QB", "RB", "WR", "TE", "K", "DST"])
    sort_by      = fc2.selectbox("Sort by", ["VOR", "Projected Pts", "ADP"])
    search_name  = fc3.text_input("Search player", "")
    show_drafted = st.checkbox("Show drafted players", value=False)

    if show_drafted or search_name:
        board = ds.all_players_with_status.copy()
    else:
        board = ds.available_players.copy()
        board["drafted"] = False

    if pos_filter != "All":
        board = board[board["position"] == pos_filter]
    if search_name:
        board = board[board["name"].str.contains(search_name, case=False, na=False)]

    # Sort — fall back to ADP when no projections exist
    has_proj = (board["projected_points"] > 0).any() if len(board) > 0 else False
    if sort_by == "ADP":
        board = board.sort_values("adp", ascending=True)
    elif not has_proj:
        board = board.sort_values("adp", ascending=True)
    elif sort_by == "VOR":
        board = board.sort_values("vor", ascending=False)
    else:
        board = board.sort_values("projected_points", ascending=False)

    # Ranked players first
    if not search_name:
        ranked   = board[board["adp"] < 999]
        unranked = board[board["adp"] >= 999]
        board    = pd.concat([ranked, unranked]).reset_index(drop=True)

    def fmt_name(row):
        return f"✓ {row['name']}" if row.get("drafted", False) else row["name"]

    disp = board.head(300).copy()
    disp["Name"]     = disp.apply(fmt_name, axis=1)
    disp["Proj Pts"] = disp["projected_points"].round(1)
    disp["VOR"]      = disp["vor"].round(1)
    disp["ADP"]      = disp["adp"].round(1)
    disp["Status"]   = disp["drafted"].apply(lambda d: "Drafted" if d else "Available")

    has_variance  = "variance_icon"   in disp.columns
    has_matchups  = "hot_start_icon"  in disp.columns
    has_playoffs  = "playoff_icon"    in disp.columns

    show_cols, col_names = ["Name", "position", "team", "Proj Pts", "VOR", "ADP"], \
                           ["Name", "Pos", "Team", "Proj Pts", "VOR", "ADP"]

    if has_variance:
        disp["Type"] = disp["variance_icon"] + " " + disp["variance_label"]
        show_cols.append("Type");  col_names.append("Type")
    if has_matchups:
        disp["Hot Start"] = disp["hot_start_icon"] + " " + disp["hot_start_label"]
        show_cols.append("Hot Start");  col_names.append("Wks 1-3")
    if has_playoffs:
        disp["Playoffs"] = disp["playoff_icon"] + " " + disp["playoff_label"]
        show_cols.append("Playoffs");  col_names.append("Wks 15-17")

    show_cols.append("Status");  col_names.append("Status")
    disp = disp[show_cols].reset_index(drop=True)
    disp.columns = col_names

    selected = st.dataframe(
        disp, use_container_width=True, hide_index=True,
        selection_mode="single-row", on_select="rerun", height=380,
    )

    sel_rows = selected.selection.rows if selected.selection else []
    if sel_rows:
        raw_sel = board.iloc[sel_rows[0]]
        if raw_sel.get("drafted", False):
            st.warning(f"**{raw_sel['name']}** has already been drafted.")
            sel_player = None
        else:
            sel_player = raw_sel
            st.info(f"Selected: **{sel_player['name']}** ({sel_player['position']} – {sel_player['team']})")
    else:
        sel_player = None

    b1, b2, b3 = st.columns(3)
    with b1:
        if st.button("✅ My Pick", type="primary",
                     disabled=(not ds.is_user_turn or sel_player is None or ds.draft_complete)):
            ds.make_pick(sel_player["player_id"])
            st.rerun()
    with b2:
        if st.button("👥 Mark as Drafted",
                     disabled=(ds.is_user_turn or sel_player is None or ds.draft_complete)):
            ds.make_pick(sel_player["player_id"])
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

        risk_cols = st.columns(4)
        for i, pos in enumerate(["QB", "RB", "WR", "TE"]):
            risk = run_risk.get(pos, {}).get("risk_level", "low")
            icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}[risk]
            risk_cols[i].caption(f"{icon} **{pos}**")
        st.caption("🔴 High · 🟡 Moderate · 🟢 Low demand ahead")
        st.write("")

        recs = ds.get_recommendations(top_n=5)
        for rec in recs:
            urgency = rec.get("urgency", "low")
            flag    = {"high": "🔴", "medium": "🟡", "low": ""}.get(urgency, "")

            with st.container(border=True):
                c1, c2 = st.columns([3, 1])
                c1.markdown(f"{flag} **{rec['name']}** — {rec['position']} ({rec['team']})")
                c2.metric("VOR", f"{rec['vor']:.1f}")
                c1.caption(f"Proj: {rec['projected_points']:.1f} pts · ADP: {rec['adp']:.1f}")

                # Variance + environment
                p_row = st.session_state.players_df[
                    st.session_state.players_df["name"] == rec["name"]
                ]
                if len(p_row) > 0:
                    badges = []
                    if "variance_icon" in p_row.columns:
                        badges.append(f"{p_row['variance_icon'].iloc[0]} {p_row['variance_label'].iloc[0]}")
                    if "env_label" in p_row.columns and p_row["env_label"].iloc[0]:
                        badges.append(p_row["env_label"].iloc[0])
                    if "hot_start_icon" in p_row.columns and p_row["hot_start_label"].iloc[0] != "Unknown":
                        badges.append(f"Wks 1-3: {p_row['hot_start_icon'].iloc[0]} {p_row['hot_start_label'].iloc[0]}")
                    if "playoff_icon" in p_row.columns and p_row["playoff_label"].iloc[0] != "Unknown":
                        badges.append(f"Wks 15-17: {p_row['playoff_icon'].iloc[0]} {p_row['playoff_label'].iloc[0]}")
                    if badges:
                        c1.caption("  ·  ".join(badges))

                st.caption(f"_{rec['reasoning']}_")

    st.subheader("📊 Position Scarcity")
    baseline_counts = get_baseline_counts(cfg)
    avail_df        = ds.available_players
    scarcity        = get_scarcity_scores(avail_df, baseline_counts)
    sc_cols = st.columns(3)
    for i, (pos, score) in enumerate(scarcity.items()):
        icon = "🔴" if score < 0.3 else "🟡" if score < 0.6 else "🟢"
        sc_cols[i % 3].metric(f"{icon} {pos}", f"{score:.0%}")

    st.subheader(f"My Roster (Team {cfg['draft_position']})")
    my_picks = ds.rosters.get(cfg["draft_position"], [])
    if my_picks:
        rdf = pd.DataFrame(my_picks)[["round", "player_name", "position"]]
        rdf.columns = ["Rd", "Player", "Pos"]
        st.dataframe(rdf, use_container_width=True, hide_index=True)
    else:
        st.caption("No picks yet.")

    # ── Roster variance profile ───────────────────────────────────────────────
    if my_picks and "variance_label" in st.session_state.players_df.columns:
        st.subheader("📊 Roster Variance Profile")
        profile = get_roster_variance_profile(my_picks, st.session_state.players_df)
        counts  = profile.get("counts", {})

        boom  = counts.get("Boom/Bust", 0)
        bal   = counts.get("Balanced",  0)
        stead = counts.get("Steady",    0)
        total = boom + bal + stead

        if total > 0:
            pc1, pc2, pc3 = st.columns(3)
            pc1.metric("🔴 Boom/Bust", boom)
            pc2.metric("🟡 Balanced",  bal)
            pc3.metric("🟢 Steady",    stead)

            # Visual bar
            avg = profile.get("avg_score", 0.5)
            bar_pct = int(avg * 100)
            st.markdown(
                f"""<div style="background:#444;border-radius:6px;height:10px;margin:4px 0 8px 0;">
                <div style="background:{'#e74c3c' if avg>0.55 else '#f39c12' if avg>0.30 else '#2ecc71'};
                            width:{bar_pct}%;height:10px;border-radius:6px;"></div></div>""",
                unsafe_allow_html=True,
            )
            st.caption(f"_{profile.get('recommendation', '')}_")

# ── All Team Compositions ─────────────────────────────────────────────────────
st.divider()
with st.expander("👥 All Team Compositions", expanded=False):
    summaries = ds.get_all_team_summaries()
    pos_list  = ["QB", "RB", "WR", "TE", "K", "DST"]

    hcols = st.columns([1] + [1] * len(pos_list))
    hcols[0].markdown("**Team**")
    for i, p in enumerate(pos_list):
        hcols[i + 1].markdown(f"**{p}**")

    for tnum in range(1, cfg["num_teams"] + 1):
        pc      = summaries[tnum]["pos_counts"]
        is_user = tnum == cfg["draft_position"]
        label   = f"Team {tnum}" + (" 👈 YOU" if is_user else "")
        rcols   = st.columns([1] + [1] * len(pos_list))
        rcols[0].markdown(f"**{label}**" if is_user else label)
        for i, p in enumerate(pos_list):
            cnt = pc.get(p, 0)
            rcols[i + 1].markdown(f"**{cnt}**" if is_user else str(cnt))

    st.write("")
    tabs = st.tabs([f"{'★ ' if t == cfg['draft_position'] else ''}Team {t}"
                    for t in range(1, cfg["num_teams"] + 1)])
    for i, tnum in enumerate(range(1, cfg["num_teams"] + 1)):
        with tabs[i]:
            picks = summaries[tnum]["picks"]
            if picks:
                tdf = pd.DataFrame(picks)[["round", "player_name", "position"]]
                tdf.columns = ["Rd", "Player", "Pos"]
                st.dataframe(tdf, use_container_width=True, hide_index=True)
            else:
                st.caption("No picks yet.")

with st.expander("📜 Full Pick Log", expanded=False):
    if ds.drafted_players:
        ldf = pd.DataFrame(ds.drafted_players)
        ldf = ldf[["pick_number", "round", "team", "player_name", "position"]]
        ldf.columns = ["Pick #", "Round", "Team", "Player", "Pos"]
        st.dataframe(ldf, use_container_width=True, hide_index=True)
    else:
        st.caption("No picks yet.")

st.divider()
if st.button("🔄 Reset Draft", type="secondary"):
    ds.reset()
    st.rerun()
