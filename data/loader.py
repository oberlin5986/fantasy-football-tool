"""
data/loader.py
--------------
Handles all data ingestion:
  - Auto-pull from Sleeper ADP (free, no key)
  - Auto-pull from FantasyPros ECR (scrape)
  - User CSV upload with fuzzy player name matching

Returns a standardized players DataFrame with columns:
  player_id, name, position, team, adp, ecr_rank,
  stats (dict of projected stat lines), projected_points (placeholder 0.0)
"""

import requests
import pandas as pd
import numpy as np
from thefuzz import process as fuzzy_process
import streamlit as st


POSITIONS = ["QB", "RB", "WR", "TE", "K", "DST"]


# ── Sleeper ADP ───────────────────────────────────────────────────────────────

@st.cache_data(ttl=3600)  # Cache for 1 hour
def fetch_sleeper_adp(scoring_type: str = "ppr") -> pd.DataFrame:
    """
    Pulls current ADP from Sleeper's free API.
    scoring_type: 'ppr' | 'half_ppr' | 'standard'
    """
    url = f"https://api.sleeper.app/v1/players/nfl"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        players = resp.json()
    except Exception as e:
        st.warning(f"Could not fetch Sleeper data: {e}. Using fallback data.")
        return pd.DataFrame()

    records = []
    for pid, p in players.items():
        pos = p.get("fantasy_positions", [None])[0]
        if pos not in POSITIONS:
            continue
        records.append({
            "player_id":  pid,
            "name":       f"{p.get('first_name', '')} {p.get('last_name', '')}".strip(),
            "position":   pos,
            "team":       p.get("team", "FA"),
            "adp":        p.get("search_rank", 999),
        })

    df = pd.DataFrame(records)
    df = df[df["team"] != "FA"]  # Remove free agents for now
    return df.sort_values("adp").reset_index(drop=True)


# ── FantasyPros ECR ───────────────────────────────────────────────────────────

@st.cache_data(ttl=3600)
def fetch_fantasypros_ecr(scoring: str = "PPR") -> pd.DataFrame:
    """
    Fetches Expert Consensus Rankings from FantasyPros.
    Returns DataFrame with ecr_rank and positional_rank columns.
    NOTE: This is a best-effort scrape. FantasyPros may rate-limit.
    """
    # TODO: Implement actual scrape when deploying
    # For now returns an empty frame that won't break the merge
    return pd.DataFrame(columns=["name", "position", "ecr_rank"])


# ── User CSV Upload ───────────────────────────────────────────────────────────

REQUIRED_STAT_COLS = {
    "QB":  ["passing_yards", "passing_tds", "interceptions", "rushing_yards", "rushing_tds"],
    "RB":  ["rushing_yards", "rushing_attempts", "rushing_tds", "receptions", "receiving_yards", "receiving_tds"],
    "WR":  ["receptions", "receiving_yards", "receiving_tds", "targets"],
    "TE":  ["receptions", "receiving_yards", "receiving_tds", "targets"],
    "K":   ["fg_0_39", "fg_40_49", "fg_50_plus", "pat_made"],
    "DST": ["dst_sack", "dst_interception", "dst_fumble_recovery", "dst_td"],
}

def parse_user_upload(uploaded_file, master_df: pd.DataFrame) -> pd.DataFrame:
    """
    Parse a user-uploaded CSV of projections.
    Required columns: player_name, position + relevant stat columns.
    Returns a DataFrame merged onto master_df with fuzzy name matching.
    """
    try:
        upload_df = pd.read_csv(uploaded_file)
    except Exception as e:
        st.error(f"Could not read file: {e}")
        return master_df

    upload_df.columns = [c.strip().lower().replace(" ", "_") for c in upload_df.columns]

    if "player_name" not in upload_df.columns:
        st.error("Upload must have a 'player_name' column.")
        return master_df

    # Fuzzy match uploaded names to master player list
    master_names = master_df["name"].tolist()
    matched_ids  = []
    unmatched    = []

    for _, row in upload_df.iterrows():
        match, score = fuzzy_process.extractOne(row["player_name"], master_names)
        if score >= 85:
            pid = master_df[master_df["name"] == match]["player_id"].iloc[0]
            matched_ids.append((row.name, pid, match, score))
        else:
            unmatched.append(row["player_name"])

    if unmatched:
        st.warning(f"Could not match {len(unmatched)} players: {', '.join(unmatched[:10])}")

    # Build stat dicts from upload rows and attach to master_df
    updated_df = master_df.copy()
    stat_cols  = [c for c in upload_df.columns if c not in ("player_name", "position", "team")]

    for row_idx, pid, matched_name, score in matched_ids:
        row = upload_df.iloc[row_idx]
        stats = {col: float(row[col]) for col in stat_cols if col in row and pd.notna(row[col])}
        mask  = updated_df["player_id"] == pid
        updated_df.loc[mask, "stats"]            = [stats] * mask.sum()
        updated_df.loc[mask, "projection_source"] = f"upload ({matched_name}, {score}%)"

    return updated_df


# ── Master loader ─────────────────────────────────────────────────────────────

def load_players(scoring_type: str = "ppr") -> pd.DataFrame:
    """
    Main entry point. Merges Sleeper ADP + ECR into a single DataFrame
    with empty stat dicts ready to be populated by uploads or future
    nflverse integration.
    """
    sleeper_df = fetch_sleeper_adp(scoring_type)

    if sleeper_df.empty:
        # Fallback: tiny placeholder so the UI doesn't break during development
        sleeper_df = _placeholder_players()

    ecr_df = fetch_fantasypros_ecr(scoring_type.upper())

    if not ecr_df.empty:
        sleeper_df = sleeper_df.merge(
            ecr_df[["name", "ecr_rank"]], on="name", how="left"
        )
    else:
        sleeper_df["ecr_rank"] = np.nan

    # Initialize empty stat dicts and computed columns
    sleeper_df["stats"]             = [{}] * len(sleeper_df)
    sleeper_df["projected_points"]  = 0.0
    sleeper_df["vor"]               = 0.0
    sleeper_df["projection_source"] = "ADP only"
    sleeper_df["drafted"]           = False

    return sleeper_df.reset_index(drop=True)


def _placeholder_players() -> pd.DataFrame:
    """Tiny placeholder dataset for offline development."""
    data = [
        ("p001", "Patrick Mahomes", "QB", "KC",  2.1),
        ("p002", "Josh Allen",      "QB", "BUF",  4.3),
        ("p003", "CeeDee Lamb",     "WR", "DAL",  5.2),
        ("p004", "Tyreek Hill",     "WR", "MIA",  7.8),
        ("p005", "Christian McCaffrey", "RB", "SF", 1.1),
        ("p006", "Breece Hall",     "RB", "NYJ",  9.4),
        ("p007", "Travis Kelce",    "TE", "KC",  11.2),
        ("p008", "Sam LaPorta",     "TE", "DET", 28.3),
        ("p009", "Justin Jefferson","WR", "MIN",  3.4),
        ("p010", "Derrick Henry",   "RB", "BAL", 14.2),
    ]
    return pd.DataFrame(data, columns=["player_id", "name", "position", "team", "adp"])
