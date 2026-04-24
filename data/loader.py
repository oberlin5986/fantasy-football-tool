"""
data/loader.py
--------------
Handles all data ingestion:
  - nflverse 2024 season stats (free, direct GitHub download)
  - Sleeper ADP (free API, no key)
  - FantasyPros ECR (scrape, best-effort)
  - User CSV upload with fuzzy name matching

Returns a standardized players DataFrame. projected_points is always
computed from stat lines + scoring settings, never stored here.
"""

import requests
import pandas as pd
import numpy as np
import io
import streamlit as st
from thefuzz import process as fuzzy_process

POSITIONS = ["QB", "RB", "WR", "TE", "K", "DST"]

# ── nflverse stats (free, GitHub releases) ────────────────────────────────────

NFLVERSE_STATS_URL = (
    "https://github.com/nflverse/nflverse-data/releases/download/player_stats/player_stats.csv"
)

@st.cache_data(ttl=86400)  # Cache 24 hrs — historical stats don't change
def fetch_nflverse_stats(season: int = 2024) -> pd.DataFrame:
    """
    Downloads nflverse season player stats and returns aggregated season totals.
    Uses the most recent completed season as a baseline for projections.
    """
    try:
        resp = requests.get(NFLVERSE_STATS_URL, timeout=30)
        resp.raise_for_status()
        df = pd.read_csv(io.StringIO(resp.text), low_memory=False)
    except Exception as e:
        st.warning(f"Could not load nflverse stats ({e}). Using ADP-only rankings.")
        return pd.DataFrame()

    # Filter to regular season for the requested year
    df = df[(df["season"] == season) & (df["season_type"] == "REG")]

    if df.empty:
        # Fall back to most recent available season
        df_all = pd.read_csv(io.StringIO(resp.text), low_memory=False)
        df_all = df_all[df_all["season_type"] == "REG"]
        latest = df_all["season"].max()
        df = df_all[df_all["season"] == latest]

    # Aggregate to season totals per player
    agg_cols = {
        "completions":       "sum",
        "attempts":          "sum",
        "passing_yards":     "sum",
        "passing_tds":       "sum",
        "interceptions":     "sum",
        "sacks":             "sum",
        "carries":           "sum",
        "rushing_yards":     "sum",
        "rushing_tds":       "sum",
        "rushing_fumbles_lost": "sum",
        "receptions":        "sum",
        "targets":           "sum",
        "receiving_yards":   "sum",
        "receiving_tds":     "sum",
        "receiving_fumbles_lost": "sum",
        "games":             "count",
    }

    # Only keep columns that exist
    agg_cols = {k: v for k, v in agg_cols.items() if k in df.columns}

    season_df = (
        df.groupby(["player_name", "position"])
          .agg(agg_cols)
          .reset_index()
    )

    # Combine fumbles lost
    season_df["fumbles_lost"] = (
        season_df.get("rushing_fumbles_lost", pd.Series(0, index=season_df.index)).fillna(0) +
        season_df.get("receiving_fumbles_lost", pd.Series(0, index=season_df.index)).fillna(0)
    )

    # Rename to match scoring engine field names
    rename = {
        "attempts":      "pass_attempts",
        "carries":       "rushing_attempts",
    }
    season_df = season_df.rename(columns={k: v for k, v in rename.items() if k in season_df.columns})

    return season_df


def build_stats_dict(row: pd.Series) -> dict:
    """Convert a nflverse aggregated row into a stats dict for scoring engine."""
    fields = [
        "completions", "pass_attempts", "passing_yards", "passing_tds",
        "interceptions", "rushing_attempts", "rushing_yards", "rushing_tds",
        "receptions", "targets", "receiving_yards", "receiving_tds", "fumbles_lost",
    ]
    return {f: float(row[f]) for f in fields if f in row.index and pd.notna(row[f])}


# ── Sleeper ADP ───────────────────────────────────────────────────────────────

@st.cache_data(ttl=3600)  # Cache 1 hr
def fetch_sleeper_adp() -> pd.DataFrame:
    """Pulls current player pool + ADP proxies from Sleeper's free API."""
    url = "https://api.sleeper.app/v1/players/nfl"
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        players = resp.json()
    except Exception as e:
        st.warning(f"Could not fetch Sleeper data: {e}. Using placeholder data.")
        return pd.DataFrame()

    records = []
    for pid, p in players.items():
        positions = p.get("fantasy_positions") or []
        pos = positions[0] if positions else None
        if pos not in POSITIONS:
            continue
        team = p.get("team")
        if not team:
            continue
        records.append({
            "player_id": pid,
            "name":      f"{p.get('first_name', '')} {p.get('last_name', '')}".strip(),
            "position":  pos,
            "team":      team,
            "adp":       p.get("search_rank") or 999,
        })

    df = pd.DataFrame(records)
    return df.sort_values("adp").reset_index(drop=True)


# ── User CSV upload ───────────────────────────────────────────────────────────

def parse_user_upload(uploaded_file, master_df: pd.DataFrame) -> pd.DataFrame:
    """
    Parse a user-uploaded CSV of projections and merge onto master_df.
    Required columns: player_name, position + any stat columns.
    """
    try:
        upload_df = pd.read_csv(uploaded_file)
    except Exception as e:
        st.error(f"Could not read file: {e}")
        return master_df

    upload_df.columns = [c.strip().lower().replace(" ", "_") for c in upload_df.columns]

    if "player_name" not in upload_df.columns:
        st.error("Upload must include a 'player_name' column.")
        return master_df

    master_names = master_df["name"].tolist()
    matched      = []
    unmatched    = []

    for idx, row in upload_df.iterrows():
        result = fuzzy_process.extractOne(row["player_name"], master_names)
        if result and result[1] >= 85:
            match_name = result[0]
            pid = master_df[master_df["name"] == match_name]["player_id"].iloc[0]
            matched.append((idx, pid))
        else:
            unmatched.append(row["player_name"])

    if unmatched:
        st.warning(f"Could not match {len(unmatched)} player(s): {', '.join(unmatched[:10])}")

    updated_df = master_df.copy()
    stat_cols  = [c for c in upload_df.columns if c not in ("player_name", "position", "team")]

    for row_idx, pid in matched:
        row   = upload_df.iloc[row_idx]
        stats = {col: float(row[col]) for col in stat_cols
                 if col in row and pd.notna(row[col])}
        mask  = updated_df["player_id"] == pid
        updated_df.loc[mask, "stats"]             = [stats] * mask.sum()
        updated_df.loc[mask, "projection_source"] = "user upload"

    return updated_df


# ── Master loader ─────────────────────────────────────────────────────────────

def load_players(scoring_type: str = "ppr") -> pd.DataFrame:
    """
    Main entry point. Builds the master player DataFrame by:
    1. Fetching Sleeper player pool + ADP
    2. Fetching nflverse 2024 season stats
    3. Fuzzy-matching stats onto the Sleeper player list
    """
    sleeper_df = fetch_sleeper_adp()

    if sleeper_df.empty:
        sleeper_df = _placeholder_players()

    # Initialize stat/point columns
    sleeper_df["stats"]             = [{}] * len(sleeper_df)
    sleeper_df["projected_points"]  = 0.0
    sleeper_df["vor"]               = 0.0
    sleeper_df["projection_source"] = "ADP only"
    sleeper_df["drafted"]           = False

    # Attach nflverse stats
    stats_df = fetch_nflverse_stats(season=2024)

    if not stats_df.empty:
        sleeper_names = sleeper_df["name"].tolist()
        matched_count = 0

        for _, stat_row in stats_df.iterrows():
            result = fuzzy_process.extractOne(stat_row["player_name"], sleeper_names)
            if result and result[1] >= 88:
                match_name = result[0]
                stats_dict = build_stats_dict(stat_row)
                if not stats_dict:
                    continue
                mask = sleeper_df["name"] == match_name
                sleeper_df.loc[mask, "stats"]             = [stats_dict] * mask.sum()
                sleeper_df.loc[mask, "projection_source"] = "nflverse 2024"
                matched_count += 1

        st.caption(f"📊 Matched {matched_count} players with 2024 stat projections.")

    return sleeper_df.reset_index(drop=True)


def _placeholder_players() -> pd.DataFrame:
    """Fallback offline dataset."""
    data = [
        ("p001", "Patrick Mahomes",     "QB",  "KC",   2.1),
        ("p002", "Josh Allen",           "QB",  "BUF",  4.3),
        ("p003", "CeeDee Lamb",          "WR",  "DAL",  5.2),
        ("p004", "Tyreek Hill",          "WR",  "MIA",  7.8),
        ("p005", "Christian McCaffrey",  "RB",  "SF",   1.1),
        ("p006", "Breece Hall",          "RB",  "NYJ",  9.4),
        ("p007", "Travis Kelce",         "TE",  "KC",  11.2),
        ("p008", "Sam LaPorta",          "TE",  "DET", 28.3),
        ("p009", "Justin Jefferson",     "WR",  "MIN",  3.4),
        ("p010", "Derrick Henry",        "RB",  "BAL", 14.2),
    ]
    return pd.DataFrame(data, columns=["player_id", "name", "position", "team", "adp"])
