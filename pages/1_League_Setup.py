"""
pages/1_League_Setup.py
-----------------------
Step 1: User enters their league configuration.
Saves to st.session_state.league_config and triggers data load.
"""

import streamlit as st
from engine.scoring import SCORING_PRESETS, DEFAULT_SCORING
from data.loader import load_players
from engine.scoring import apply_scoring_to_df
from engine.vorp import calculate_vor

st.set_page_config(page_title="League Setup", page_icon="⚙️", layout="wide")
st.title("⚙️ League Setup")
st.markdown("Configure your league settings. These drive all player valuations.")

# ── Layout ────────────────────────────────────────────────────────────────────
col_left, col_right = st.columns(2)

with col_left:
    st.subheader("League Basics")

    num_teams = st.selectbox("Number of Teams", [8, 10, 12, 14], index=2)
    draft_position = st.number_input("Your Draft Position", min_value=1, max_value=num_teams, value=1)
    draft_type = st.selectbox("Draft Type", ["Snake", "Auction"], index=0)
    total_rounds = st.number_input("Total Draft Rounds", min_value=10, max_value=20, value=15)

    st.subheader("Scoring Format")
    scoring_preset = st.selectbox(
        "Scoring Preset",
        ["Standard", "Half-PPR", "PPR", "Custom"],
        index=2,
        help="PPR = 1 point per reception. Choose Custom to set your own values."
    )

with col_right:
    st.subheader("Roster Slots")
    qb_slots  = st.number_input("QB",       min_value=1, max_value=3,  value=1)
    rb_slots  = st.number_input("RB",       min_value=1, max_value=4,  value=2)
    wr_slots  = st.number_input("WR",       min_value=1, max_value=4,  value=2)
    te_slots  = st.number_input("TE",       min_value=1, max_value=2,  value=1)
    flex_slots = st.number_input("FLEX (RB/WR/TE)", min_value=0, max_value=3, value=1)
    sf_slots  = st.number_input("SuperFlex (QB/RB/WR/TE)", min_value=0, max_value=2, value=0)
    k_slots   = st.number_input("K",        min_value=0, max_value=2,  value=1)
    dst_slots = st.number_input("DST",      min_value=0, max_value=2,  value=1)
    bench_slots = st.number_input("Bench",  min_value=4, max_value=10, value=6)

# ── Custom scoring ────────────────────────────────────────────────────────────
if scoring_preset == "Custom":
    st.subheader("Custom Scoring Settings")
    base = DEFAULT_SCORING.copy()
    c1, c2, c3 = st.columns(3)

    with c1:
        st.markdown("**Passing**")
        base["passing_yards_per_point"] = st.number_input("Yards per passing pt", value=25, min_value=1)
        base["passing_td"]  = st.number_input("Passing TD pts", value=4.0, step=0.5)
        base["interception"] = st.number_input("Interception pts", value=-2.0, step=0.5)

    with c2:
        st.markdown("**Rushing / Receiving**")
        base["rushing_yards_per_point"]   = st.number_input("Yards per rush pt",   value=10, min_value=1)
        base["rushing_td"]    = st.number_input("Rushing TD pts",   value=6.0, step=0.5)
        base["reception"]     = st.number_input("Points per reception", value=1.0, step=0.5)
        base["receiving_yards_per_point"] = st.number_input("Yards per rec pt",    value=10, min_value=1)
        base["receiving_td"]  = st.number_input("Receiving TD pts", value=6.0, step=0.5)

    with c3:
        st.markdown("**Misc**")
        base["fumble_lost"] = st.number_input("Fumble lost pts", value=-2.0, step=0.5)
        base["fg_0_39"]     = st.number_input("FG 0-39 yds", value=3.0, step=0.5)
        base["fg_40_49"]    = st.number_input("FG 40-49 yds", value=4.0, step=0.5)
        base["fg_50_plus"]  = st.number_input("FG 50+ yds",   value=5.0, step=0.5)

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
            "qb":       qb_slots,
            "rb":       rb_slots,
            "wr":       wr_slots,
            "te":       te_slots,
            "flex":     flex_slots,
            "superflex": sf_slots,
            "k":        k_slots,
            "dst":      dst_slots,
            "bench":    bench_slots,
        }
    }

    with st.spinner("Loading player data..."):
        scoring_type = {"Standard": "standard", "Half-PPR": "half_ppr"}.get(
            scoring_preset, "ppr"
        )
        players_df = load_players(scoring_type)
        players_df = apply_scoring_to_df(players_df, custom_scoring)
        players_df = calculate_vor(players_df, league_config)

    st.session_state.league_config = league_config
    st.session_state.players_df    = players_df
    st.session_state.draft_started = False  # Reset any active draft
    st.session_state.draft_state   = None

    st.success(f"✅ League configured! Loaded {len(players_df)} players.")
    st.info("Head to **Draft Board** to start drafting, or **Simulator** to practice.")

# ── Show current config if already set ───────────────────────────────────────
if st.session_state.league_config:
    with st.expander("Current League Config", expanded=False):
        cfg = st.session_state.league_config
        st.json({k: v for k, v in cfg.items() if k != "scoring"})
