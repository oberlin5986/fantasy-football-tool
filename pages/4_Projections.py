"""
pages/4_Projections.py
----------------------
Manage projection data: view current source, upload custom CSV,
refresh from free sources, or download the CSV template.
"""

import io
import streamlit as st
import pandas as pd
from data.loader import load_players, parse_user_upload, REQUIRED_STAT_COLS
from engine.scoring import apply_scoring_to_df
from engine.vorp import calculate_vor

st.set_page_config(page_title="Projections", page_icon="📈", layout="wide")
st.title("📈 Projections")

if not st.session_state.get("league_config"):
    st.warning("⚠️ Complete **League Setup** first.")
    st.stop()

cfg = st.session_state.league_config

# ── Current data status ───────────────────────────────────────────────────────
st.subheader("Current Data")

if st.session_state.players_df is not None:
    df = st.session_state.players_df
    sources = df["projection_source"].value_counts()
    c1, c2, c3 = st.columns(3)
    c1.metric("Total Players", len(df))
    c2.metric("With Stat Projections", int((df["projected_points"] > 0).sum()))
    c3.metric("ADP-only Players", int((df["projected_points"] == 0).sum()))
    st.caption("Sources: " + " | ".join(f"{k}: {v}" for k, v in sources.items()))
else:
    st.info("No data loaded yet. Go to League Setup to load player data.")

st.divider()

# ── Refresh free data ─────────────────────────────────────────────────────────
st.subheader("🔄 Refresh Free Data")
st.markdown("Pulls latest ADP from Sleeper and ECR from FantasyPros. Updates automatically every hour.")

if st.button("Refresh Now", use_container_width=False):
    with st.spinner("Refreshing..."):
        scoring_type = {"Standard": "standard", "Half-PPR": "half_ppr"}.get(
            cfg["scoring_preset"], "ppr"
        )
        # Clear cache so fresh data is fetched
        load_players.clear()
        players_df = load_players(scoring_type)
        players_df = apply_scoring_to_df(players_df, cfg["scoring"])
        players_df = calculate_vor(players_df, cfg)
        st.session_state.players_df = players_df
    st.success("✅ Data refreshed!")

st.divider()

# ── Upload custom projections ─────────────────────────────────────────────────
st.subheader("📤 Upload Custom Projections")
st.markdown("""
Upload a CSV with your own projection data. The more stat columns you provide,
the more accurately the tool can apply your league's scoring settings.
""")

# Template download
st.markdown("**Download CSV Template:**")
template_cols = (
    ["player_name", "position", "team"] +
    ["passing_yards","passing_tds","interceptions","rushing_yards","rushing_tds",
     "receptions","receiving_yards","receiving_tds","targets","fumbles_lost",
     "fg_0_39","fg_40_49","fg_50_plus","pat_made"]
)
template_df = pd.DataFrame(columns=template_cols)
csv_bytes = template_df.to_csv(index=False).encode()
st.download_button(
    "⬇️ Download Template CSV",
    data=csv_bytes,
    file_name="projection_template.csv",
    mime="text/csv",
)

st.markdown("---")
uploaded = st.file_uploader("Upload your projections CSV", type=["csv"])

if uploaded:
    with st.spinner("Processing upload and matching players..."):
        if st.session_state.players_df is None:
            st.error("Load player data from League Setup first.")
        else:
            updated_df = parse_user_upload(uploaded, st.session_state.players_df)
            updated_df = apply_scoring_to_df(updated_df, cfg["scoring"])
            updated_df = calculate_vor(updated_df, cfg)
            st.session_state.players_df = updated_df
    st.success("✅ Projections uploaded and applied!")

st.divider()

# ── Preview player data ───────────────────────────────────────────────────────
st.subheader("Player Data Preview")

if st.session_state.players_df is not None:
    pos_tab = st.selectbox("Position", ["All"] + ["QB","RB","WR","TE","K","DST"])
    preview = st.session_state.players_df.copy()

    if pos_tab != "All":
        preview = preview[preview["position"] == pos_tab]

    preview = preview.sort_values("vor", ascending=False)
    cols = ["name","position","team","projected_points","vor","adp","projection_source"]
    st.dataframe(preview[cols].head(50), use_container_width=True, hide_index=True)
