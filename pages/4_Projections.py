"""
pages/4_Projections.py
----------------------
Manage projection data:
  - Auto-pull from ESPN Fantasy API
  - Manual upload from FantasyPros or any CSV source
  - View current projection coverage
"""

import io
import streamlit as st
import pandas as pd
from data.loader import load_players, parse_user_upload, ESPN_SEASON, fetch_espn_projections, fetch_sleeper_adp
from engine.scoring import apply_scoring_to_df
from engine.vorp import calculate_vor

st.set_page_config(page_title="Projections", page_icon="📈", layout="wide")
st.title("📈 Projections")

if not st.session_state.get("league_config"):
    st.warning("⚠️ Complete **League Setup** first.")
    st.stop()

cfg = st.session_state.league_config

# ── Current data status ───────────────────────────────────────────────────────
st.subheader("Current Data Status")

if st.session_state.players_df is not None:
    df      = st.session_state.players_df
    sources = df["projection_source"].value_counts()
    with_proj = int((df["projected_points"] > 0).sum())
    adp_only  = int((df["projected_points"] == 0).sum())

    c1, c2, c3 = st.columns(3)
    c1.metric("Total Players",        len(df))
    c2.metric("With Stat Projections", with_proj)
    c3.metric("ADP-only",              adp_only)

    if with_proj > 0:
        st.success(f"✅ Projections active — sourced from: {', '.join(sources.index.tolist())}")
    else:
        st.warning("⚠️ No stat projections loaded yet — rankings are ADP-based only. "
                   "Use one of the options below to load projections.")
else:
    st.info("No data loaded yet. Go to **League Setup** first.")

st.divider()

# ── Section 1: ESPN Auto-Pull ─────────────────────────────────────────────────
st.subheader(f"🏈 ESPN Fantasy Projections (Auto · {ESPN_SEASON} Season)")
st.markdown(f"""
Pulls current **{ESPN_SEASON} season projections** directly from ESPN's Fantasy API.
Free, no account needed. Updates as ESPN refreshes their preseason projections.
Stat lines are applied per your league's scoring settings automatically.
""")

col_a, col_b = st.columns([2, 1])
with col_a:
    st.info(
        "**How it works:** ESPN projections include passing yards, TDs, "
        "rush yards, receptions, receiving yards, and more — all the stat lines "
        "your league scoring settings need to calculate accurate fantasy points."
    )
with col_b:
    if st.button("🔄 Pull ESPN Projections Now", type="primary", use_container_width=True):
        with st.spinner(f"Fetching ESPN {ESPN_SEASON} projections..."):
            scoring_type = {"Standard": "standard", "Half-PPR": "half_ppr"}.get(
                cfg["scoring_preset"], "ppr"
            )
             # Clear the underlying cached functions to force fresh fetch
            fetch_espn_projections.clear()
            fetch_sleeper_adp.clear()
            players_df = load_players(scoring_type)
            players_df = apply_scoring_to_df(players_df, cfg["scoring"])
            players_df = calculate_vor(players_df, cfg)
            st.session_state.players_df    = players_df
            st.session_state.draft_state   = None
            st.session_state.sim_state     = None
        proj_count = int((players_df["projected_points"] > 0).sum())
        if proj_count > 0:
            st.success(f"✅ ESPN projections loaded — {proj_count} players with stat lines!")
        else:
            st.warning(
                "ESPN data loaded but no projections found. "
                "This can happen early in the offseason before ESPN publishes "
                f"{ESPN_SEASON} projections. Try uploading FantasyPros projections below."
            )

st.caption(
    "⚠️ ESPN's Fantasy API is unofficial and undocumented. "
    "It may occasionally be unavailable. If it fails, use the manual upload below."
)

st.divider()

# ── Section 2: FantasyPros Manual Upload ──────────────────────────────────────
st.subheader("📥 Upload FantasyPros Projections (Recommended for Accuracy)")

with st.expander("📖 Step-by-step instructions — click to expand", expanded=False):
    st.markdown(f"""
### How to download projections from FantasyPros

FantasyPros publishes free season-long projections that are updated regularly
throughout the preseason. Follow these steps for each position:

---

**Step 1 — Go to each projection page:**

| Position | URL |
|---|---|
| QB | `fantasypros.com/nfl/projections/qb.php` |
| RB | `fantasypros.com/nfl/projections/rb.php` |
| WR | `fantasypros.com/nfl/projections/wr.php` |
| TE | `fantasypros.com/nfl/projections/te.php` |
| K  | `fantasypros.com/nfl/projections/k.php`  |

**Step 2 — Set the time period:**
- Look for a dropdown near the top of the page
- Select **"Season"** (not a specific week)

**Step 3 — Export:**
- Click the **"Export"** button (usually top-right of the table)
- This downloads a `.csv` file (e.g. `FantasyPros_Fantasy_Football_Projections_QB.csv`)

**Step 4 — Combine into one file:**
- Open all the CSV files and copy-paste the rows into a single file
- Keep only one header row at the top
- Save as a `.csv`

**Step 5 — Upload below**

The uploader will automatically detect FantasyPros column names and remap them.
No manual column renaming needed.

---

**FantasyPros column names and what they map to:**

| FantasyPros | Stat |
|---|---|
| PASS YDS | Passing yards |
| PASS TDS | Passing TDs |
| PASS INTS | Interceptions thrown |
| RUSH ATT | Rushing attempts |
| RUSH YDS | Rushing yards |
| RUSH TDS | Rushing TDs |
| REC | Receptions |
| REC YDS | Receiving yards |
| REC TDS | Receiving TDs |
| FL | Fumbles lost |
""")

uploaded = st.file_uploader(
    "Upload your FantasyPros or custom CSV",
    type=["csv"],
    help="FantasyPros exports work automatically. For custom files, use our template below."
)

if uploaded:
    if st.session_state.players_df is None:
        st.error("Load player data from League Setup first.")
    else:
        with st.spinner("Processing and matching players..."):
            updated_df = parse_user_upload(uploaded, st.session_state.players_df)
            updated_df = apply_scoring_to_df(updated_df, cfg["scoring"])
            updated_df = calculate_vor(updated_df, cfg)
            st.session_state.players_df  = updated_df
            st.session_state.draft_state = None
            st.session_state.sim_state   = None
        proj_count = int((updated_df["projected_points"] > 0).sum())
        st.success(f"✅ Upload applied — {proj_count} players now have stat projections!")

# Template download
st.markdown("**Need a blank template instead?**")
template_cols = [
    "player_name", "position", "team",
    "passing_yards", "passing_tds", "interceptions", "pass_attempts", "completions",
    "rushing_yards", "rushing_attempts", "rushing_tds",
    "receptions", "receiving_yards", "receiving_tds", "targets", "fumbles_lost",
    "fg_0_39", "fg_40_49", "fg_50_plus", "pat_made",
]
csv_bytes = pd.DataFrame(columns=template_cols).to_csv(index=False).encode()
st.download_button(
    "⬇️ Download Blank Template CSV",
    data=csv_bytes,
    file_name="projection_template.csv",
    mime="text/csv",
)

st.divider()

# ── Section 3: Data Preview ───────────────────────────────────────────────────
st.subheader("Player Data Preview")

if st.session_state.players_df is not None:
    pos_filter = st.selectbox("Filter by position", ["All", "QB", "RB", "WR", "TE", "K", "DST"])
    preview    = st.session_state.players_df.copy()

    if pos_filter != "All":
        preview = preview[preview["position"] == pos_filter]

    preview = preview.sort_values("vor", ascending=False)
    show_cols = ["name", "position", "team", "projected_points", "vor", "adp", "projection_source"]
    st.dataframe(
        preview[show_cols].head(60).rename(columns={
            "name": "Player", "position": "Pos", "team": "Team",
            "projected_points": "Proj Pts", "vor": "VOR",
            "adp": "ADP", "projection_source": "Source"
        }),
        use_container_width=True,
        hide_index=True,
    )
