"""
pages/4_Projections.py
----------------------
Manage projection data:
  - Auto-pull from ESPN Fantasy API
  - Manual upload from FantasyPros or any CSV source
  - Diagnostic tool to inspect ESPN API response structure
"""

import io
import json
import requests
import streamlit as st
import pandas as pd
from data.loader import (
    load_players, parse_user_upload, ESPN_SEASON,
    fetch_espn_projections, fetch_sleeper_adp
)
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
    df        = st.session_state.players_df
    sources   = df["projection_source"].value_counts()
    with_proj = int((df["projected_points"] > 0).sum())
    adp_only  = int((df["projected_points"] == 0).sum())

    c1, c2, c3 = st.columns(3)
    c1.metric("Total Players",         len(df))
    c2.metric("With Stat Projections", with_proj)
    c3.metric("ADP-only",              adp_only)

    if with_proj > 0:
        st.success(f"✅ Projections active — sourced from: {', '.join(sources.index.tolist())}")
    else:
        st.warning("⚠️ No stat projections loaded yet — rankings are ADP-based only.")
else:
    st.info("No data loaded yet. Go to **League Setup** first.")

st.divider()

# ── Section 1: ESPN Auto-Pull ─────────────────────────────────────────────────
st.subheader(f"🏈 ESPN Fantasy Projections (Auto · {ESPN_SEASON} Season)")
st.markdown(
    f"Pulls current **{ESPN_SEASON} season projections** from ESPN's Fantasy API. "
    "Free, no account needed."
)

col_a, col_b = st.columns([2, 1])
with col_a:
    st.info(
        "Includes passing yards, TDs, rush yards, receptions, receiving yards, "
        "and more — all stat lines your league scoring settings need."
    )
with col_b:
    if st.button("🔄 Pull ESPN Projections Now", type="primary", use_container_width=True):
        with st.spinner(f"Fetching ESPN {ESPN_SEASON} projections..."):
            scoring_type = {"Standard": "standard", "Half-PPR": "half_ppr"}.get(
                cfg["scoring_preset"], "ppr"
            )
            fetch_espn_projections.clear()
            fetch_sleeper_adp.clear()
            players_df = load_players(scoring_type)
            players_df = apply_scoring_to_df(players_df, cfg["scoring"])
            players_df = calculate_vor(players_df, cfg)
            st.session_state.players_df  = players_df
            st.session_state.draft_state = None
            st.session_state.sim_state   = None
        proj_count = int((players_df["projected_points"] > 0).sum())
        if proj_count > 0:
            st.success(f"✅ ESPN projections loaded — {proj_count} players with stat lines!")
        else:
            st.warning(
                "ESPN data loaded but no projections found. "
                "Run the diagnostic below to see what ESPN is returning."
            )

st.caption("⚠️ ESPN's Fantasy API is unofficial. Use the diagnostic below if projections aren't loading.")

# ── ESPN Diagnostic ───────────────────────────────────────────────────────────
with st.expander("🔍 ESPN API Diagnostic — click here if projections aren't loading", expanded=False):
    st.markdown(
        "Fetches 3 players from ESPN and shows the **raw response structure** "
        "so we can pinpoint exactly where the stats live and fix the parser."
    )
    if st.button("▶️ Run Diagnostic", key="espn_diag"):
        url = f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{ESPN_SEASON}/players"

        # Broaden the filter to catch all statSourceId and splitTypeId values
        xff = json.dumps({
            "players": {
                "limit": 3,
                "filterStatsForSourceIds":    {"value": [0, 1, 2]},
                "filterStatsForSplitTypeIds": {"value": [0, 1, 2]},
                "sortDraftRanks": {
                    "sortPriority": 100,
                    "sortAsc": True,
                    "value": "PPR",
                },
            }
        })
        headers = {
            "X-Fantasy-Filter": xff,
            "User-Agent": "Mozilla/5.0",
            "Accept":     "application/json",
        }
        params = {"scoringPeriodId": 0, "view": "kona_player_info"}

        try:
            resp = requests.get(url, headers=headers, params=params, timeout=20)
            st.write(f"**HTTP Status:** `{resp.status_code}`")
            data = resp.json()

            if isinstance(data, list):
                st.write(f"**Response type:** list · **Length:** {len(data)}")
                players = data
            elif isinstance(data, dict):
                st.write(f"**Response type:** dict · **Top-level keys:** `{list(data.keys())}`")
                players = data.get("players", [])
            else:
                st.error(f"Unexpected response type: {type(data)}")
                st.stop()

            st.write(f"**Players returned:** {len(players)}")

            if not players:
                st.warning("ESPN returned no players. Raw response:")
                st.json(data if isinstance(data, dict) else {})
            else:
                for i, entry in enumerate(players[:2]):
                    pool = entry.get("playerPoolEntry", {})
                    plyr = pool.get("player", {})
                    name = plyr.get("fullName", f"Player {i}")
                    st.markdown(f"---\n**Player {i+1}: {name}**")

                    # Show all stat blocks with their IDs and sample values
                    stats_arr = plyr.get("stats", [])
                    st.write(f"  `player.stats` blocks: {len(stats_arr)}")
                    for sb in stats_arr:
                        src   = sb.get("statSourceId", "?")
                        split = sb.get("statSplitTypeId", "?")
                        inner = sb.get("stats", sb.get("appliedStats", {}))
                        sample = dict(list(inner.items())[:8]) if inner else "empty"
                        st.write(f"  statSourceId=**{src}** · statSplitTypeId=**{split}** → `{sample}`")

                    # Also show pool-level keys in case total is stored there
                    pool_keys = [k for k in pool.keys() if "stat" in k.lower() or "proj" in k.lower() or "total" in k.lower()]
                    if pool_keys:
                        st.write(f"  playerPoolEntry projection keys: `{pool_keys}`")
                        for k in pool_keys:
                            st.write(f"    `{k}`: {pool[k]}")

        except Exception as e:
            st.error(f"Request failed: {e}")

st.divider()

# ── Section 2: FantasyPros Manual Upload ──────────────────────────────────────
st.subheader("📥 Upload FantasyPros Projections (Recommended for Accuracy)")

with st.expander("📖 Step-by-step instructions", expanded=False):
    st.markdown(f"""
### How to download projections from FantasyPros

**Step 1 — Go to each projection page** (copy into your browser):

| Position | URL |
|---|---|
| QB | `fantasypros.com/nfl/projections/qb.php` |
| RB | `fantasypros.com/nfl/projections/rb.php` |
| WR | `fantasypros.com/nfl/projections/wr.php` |
| TE | `fantasypros.com/nfl/projections/te.php` |
| K  | `fantasypros.com/nfl/projections/k.php`  |

**Step 2 — Set the time period** to **"Season"** (not a specific week)

**Step 3 — Export:** click the **Export** button (top-right of the table) → downloads a CSV

**Step 4 — Combine:** open all CSVs, copy rows into one file with a single header row, save as CSV

**Step 5 — Upload below** — FantasyPros column names are detected and remapped automatically

---

**Column mapping (handled automatically):**

| FantasyPros | Internal stat |
|---|---|
| PASS YDS | passing_yards |
| PASS TDS | passing_tds |
| PASS INTS | interceptions |
| RUSH ATT | rushing_attempts |
| RUSH YDS | rushing_yards |
| RUSH TDS | rushing_tds |
| REC | receptions |
| REC YDS | receiving_yards |
| REC TDS | receiving_tds |
| FL | fumbles_lost |
""")

uploaded = st.file_uploader(
    "Upload FantasyPros CSV or custom file",
    type=["csv"],
    help="FantasyPros exports are auto-detected. For custom files use the template below."
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

st.markdown("**Need a blank template?**")
template_cols = [
    "player_name", "position", "team",
    "passing_yards", "passing_tds", "interceptions", "pass_attempts", "completions",
    "rushing_yards", "rushing_attempts", "rushing_tds",
    "receptions", "receiving_yards", "receiving_tds", "targets", "fumbles_lost",
    "fg_0_39", "fg_40_49", "fg_50_plus", "pat_made",
]
csv_bytes = pd.DataFrame(columns=template_cols).to_csv(index=False).encode()
st.download_button("⬇️ Download Blank Template CSV", data=csv_bytes,
                   file_name="projection_template.csv", mime="text/csv")

st.divider()

# ── Section 3: Data Preview ───────────────────────────────────────────────────
st.subheader("Player Data Preview")

if st.session_state.players_df is not None:
    pos_filter = st.selectbox("Filter by position", ["All", "QB", "RB", "WR", "TE", "K", "DST"])
    preview    = st.session_state.players_df.copy()
    if pos_filter != "All":
        preview = preview[preview["position"] == pos_filter]
    preview = preview.sort_values("vor", ascending=False)
    show = ["name", "position", "team", "projected_points", "vor", "adp", "projection_source"]
    st.dataframe(
        preview[show].head(60).rename(columns={
            "name": "Player", "position": "Pos", "team": "Team",
            "projected_points": "Proj Pts", "vor": "VOR",
            "adp": "ADP", "projection_source": "Source",
        }),
        use_container_width=True, hide_index=True,
    )
