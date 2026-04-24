"""
pages/1_League_Setup.py
-----------------------
League configuration. Total rounds auto-calculated from roster slots.
"""

import streamlit as st
from engine.scoring import SCORING_PRESETS, DEFAULT_SCORING
from data.loader import load_players, fetch_nflverse_weekly
from engine.scoring import apply_scoring_to_df
from engine.vorp import calculate_vor
from engine.variance import apply_variance_to_df, build_weekly_std_map

st.set_page_config(page_title="League Setup", page_icon="⚙️", layout="wide")
st.title("⚙️ League Setup")
st.markdown("Configure your league. Total draft rounds update automatically as you adjust roster slots.")

col_left, col_right = st.columns(2)

with col_left:
    st.subheader("League Basics")
    num_teams      = st.selectbox("Number of Teams", [8, 10, 12, 14], index=2)
    draft_position = st.number_input("Your Draft Position", min_value=1, max_value=num_teams, value=1)
    draft_type     = st.selectbox("Draft Type", ["Snake", "Auction"], index=0)

    st.subheader("Scoring Format")
    scoring_preset = st.selectbox(
        "Scoring Preset",
        ["Standard", "Half-PPR", "PPR", "Custom"],
        index=2,
        help="PPR = 1 pt per reception. Choose Custom to set individual values."
    )

with col_right:
    st.subheader("Roster Slots")
    qb_slots    = st.number_input("QB",                        min_value=1, max_value=3,  value=1)
    rb_slots    = st.number_input("RB",                        min_value=1, max_value=4,  value=2)
    wr_slots    = st.number_input("WR",                        min_value=1, max_value=4,  value=2)
    te_slots    = st.number_input("TE",                        min_value=1, max_value=2,  value=1)
    flex_slots  = st.number_input("FLEX (RB/WR/TE)",           min_value=0, max_value=3,  value=1)
    sf_slots    = st.number_input("SuperFlex (QB/RB/WR/TE)",   min_value=0, max_value=2,  value=0)
    k_slots     = st.number_input("K",                         min_value=0, max_value=2,  value=1)
    dst_slots   = st.number_input("DST",                       min_value=0, max_value=2,  value=1)
    bench_slots = st.number_input("Bench",                     min_value=1, max_value=12, value=6)

    # Auto-calculate total rounds
    total_rounds = qb_slots + rb_slots + wr_slots + te_slots + flex_slots + sf_slots + k_slots + dst_slots + bench_slots
    st.metric("Total Draft Rounds (auto)", total_rounds, help="Sum of all roster slots")

# ── Custom scoring ────────────────────────────────────────────────────────────
if scoring_preset == "Custom":
    st.divider()
    st.subheader("Custom Scoring Settings")
    base = DEFAULT_SCORING.copy()

    tab_pass, tab_rush, tab_rec, tab_kicker, tab_dst = st.tabs(
        ["🏈 Passing", "🏃 Rushing", "🤲 Receiving", "🦵 Kicker", "🛡️ DST"]
    )

    with tab_pass:
        c1, c2 = st.columns(2)
        with c1:
            base["passing_yards_per_point"] = st.number_input("Yards per pt (passing)",    value=25,   min_value=1, step=1)
            base["passing_td"]              = st.number_input("Passing TD",                value=4.0,  step=0.5)
            base["interception"]            = st.number_input("Interception",              value=-2.0, step=0.5)
        with c2:
            base["completion_bonus"]        = st.number_input("Pts per completion",        value=0.0,  step=0.05,
                                                               help="e.g. 0.1 in some DFS/leagues")
            base["passing_attempt_bonus"]   = st.number_input("Pts per pass attempt",      value=0.0,  step=0.05)
            base["bonus_pass_300"]          = st.number_input("Bonus: 300+ pass yds game", value=0.0,  step=0.5)
            base["bonus_pass_400"]          = st.number_input("Bonus: 400+ pass yds game", value=0.0,  step=0.5)

    with tab_rush:
        c1, c2 = st.columns(2)
        with c1:
            base["rushing_yards_per_point"] = st.number_input("Yards per pt (rushing)",    value=10,   min_value=1, step=1)
            base["rushing_td"]              = st.number_input("Rushing TD",                value=6.0,  step=0.5)
        with c2:
            base["rushing_attempt_bonus"]   = st.number_input("Pts per rush attempt",      value=0.0,  step=0.05,
                                                               help="Rare but used in some leagues")
            base["bonus_rush_100"]          = st.number_input("Bonus: 100+ rush yds game", value=0.0,  step=0.5)
            base["bonus_rush_200"]          = st.number_input("Bonus: 200+ rush yds game", value=0.0,  step=0.5)
            base["fumble_lost"]             = st.number_input("Fumble lost",               value=-2.0, step=0.5)

    with tab_rec:
        c1, c2 = st.columns(2)
        with c1:
            base["reception"]                = st.number_input("Pts per reception (PPR)",   value=1.0,  step=0.5)
            base["receiving_yards_per_point"] = st.number_input("Yards per pt (receiving)", value=10,   min_value=1, step=1)
            base["receiving_td"]             = st.number_input("Receiving TD",              value=6.0,  step=0.5)
        with c2:
            base["target_bonus"]             = st.number_input("Pts per target",            value=0.0,  step=0.05,
                                                                help="Some leagues reward targets")
            base["bonus_rec_100"]            = st.number_input("Bonus: 100+ rec yds game",  value=0.0,  step=0.5)
            base["bonus_rec_200"]            = st.number_input("Bonus: 200+ rec yds game",  value=0.0,  step=0.5)

    with tab_kicker:
        c1, c2 = st.columns(2)
        with c1:
            base["fg_0_39"]   = st.number_input("FG 0–39 yds",  value=3.0, step=0.5)
            base["fg_40_49"]  = st.number_input("FG 40–49 yds", value=4.0, step=0.5)
            base["fg_50_plus"] = st.number_input("FG 50+ yds",  value=5.0, step=0.5)
        with c2:
            base["pat_made"]   = st.number_input("PAT made",    value=1.0, step=0.5)
            base["pat_missed"] = st.number_input("PAT missed",  value=-1.0, step=0.5)
            base["fg_missed"]  = st.number_input("FG missed",   value=-1.0, step=0.5)

    with tab_dst:
        c1, c2 = st.columns(2)
        with c1:
            base["dst_sack"]              = st.number_input("Sack",              value=1.0, step=0.5)
            base["dst_interception"]      = st.number_input("Interception",      value=2.0, step=0.5)
            base["dst_fumble_recovery"]   = st.number_input("Fumble recovery",   value=2.0, step=0.5)
            base["dst_td"]                = st.number_input("Defensive TD",      value=6.0, step=0.5)
            base["dst_safety"]            = st.number_input("Safety",            value=2.0, step=0.5)
        with c2:
            base["dst_points_allowed_0"]      = st.number_input("Pts allowed: 0",      value=10.0, step=0.5)
            base["dst_points_allowed_1_6"]    = st.number_input("Pts allowed: 1–6",    value=7.0,  step=0.5)
            base["dst_points_allowed_7_13"]   = st.number_input("Pts allowed: 7–13",   value=4.0,  step=0.5)
            base["dst_points_allowed_14_20"]  = st.number_input("Pts allowed: 14–20",  value=1.0,  step=0.5)
            base["dst_points_allowed_21_27"]  = st.number_input("Pts allowed: 21–27",  value=0.0,  step=0.5)
            base["dst_points_allowed_28_34"]  = st.number_input("Pts allowed: 28–34",  value=-1.0, step=0.5)
            base["dst_points_allowed_35_plus"] = st.number_input("Pts allowed: 35+",   value=-4.0, step=0.5)

    custom_scoring = base
else:
    custom_scoring = SCORING_PRESETS[scoring_preset]

# ── Save & Load ───────────────────────────────────────────────────────────────
st.divider()

if st.button("💾 Save Settings & Load Player Data", type="primary", use_container_width=True):
    league_config = {
        "num_teams":      num_teams,
        "draft_position": draft_position,
        "draft_type":     draft_type.lower(),
        "total_rounds":   total_rounds,
        "scoring":        custom_scoring,
        "scoring_preset": scoring_preset,
        "roster_slots": {
            "qb":        qb_slots,
            "rb":        rb_slots,
            "wr":        wr_slots,
            "te":        te_slots,
            "flex":      flex_slots,
            "superflex": sf_slots,
            "k":         k_slots,
            "dst":       dst_slots,
            "bench":     bench_slots,
        }
    }

    with st.spinner("Loading players, projections and variance profiles..."):
        scoring_type = {"Standard": "standard", "Half-PPR": "half_ppr"}.get(
            scoring_preset, "ppr"
        )
        players_df = load_players(scoring_type)
        players_df = apply_scoring_to_df(players_df, custom_scoring)
        players_df = calculate_vor(players_df, league_config)

        # Build historical std dev map from nflverse weekly data
        weekly_df  = fetch_nflverse_weekly(season=2025)
        if not weekly_df.empty:
            weekly_std_map = build_weekly_std_map(weekly_df, custom_scoring)
        else:
            weekly_std_map = None

        # Apply boom/bust/steady variance profiles
        players_df = apply_variance_to_df(players_df, custom_scoring,
                                          weekly_std_map=weekly_std_map)

    st.session_state.league_config = league_config
    st.session_state.players_df    = players_df
    st.session_state.draft_started = False
    st.session_state.draft_state   = None
    st.session_state.sim_state     = None

    has_proj  = int((players_df["projected_points"] > 0).sum())
    has_var   = int((players_df["variance_label"] != "Balanced").sum())
    st.success(f"✅ Loaded {len(players_df)} players — {has_proj} with projections, {has_var} with variance profiles.")
    st.info("Head to **Draft Board** to draft, or **Simulator** to practice.")

if st.session_state.get("league_config"):
    with st.expander("Current League Config", expanded=False):
        cfg = st.session_state.league_config
        st.json({k: v for k, v in cfg.items() if k != "scoring"})
