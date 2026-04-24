"""
data/loader.py
--------------
Data ingestion layers (in priority order):
  1. ESPN Fantasy API  — free, no key, current-season projections (stat lines)
  2. Sleeper API       — free, no key, player pool + ADP
  3. User CSV upload   — any source, fuzzy name matching

projected_points is NEVER stored here — always computed fresh by scoring engine.
"""

import json
import requests
import pandas as pd
import io
import streamlit as st
from thefuzz import process as fuzzy_process

POSITIONS  = ["QB", "RB", "WR", "TE", "K", "DST"]
ESPN_SEASON = 2026   # Update each year

# ── ESPN stat ID → our internal stat name ────────────────────────────────────
# These IDs are from the undocumented ESPN Fantasy API (community-documented).
# ESPN returns stats as a dict keyed by numeric string IDs.
ESPN_STAT_MAP = {
    "0":  "pass_attempts",
    "1":  "completions",
    "3":  "passing_yards",
    "4":  "passing_tds",
    "20": "interceptions",      # INTs thrown
    "23": "rushing_attempts",
    "24": "rushing_yards",
    "25": "rushing_tds",
    "41": "receptions",
    "42": "receiving_yards",
    "43": "receiving_tds",
    "72": "fumbles_lost",
    # Kicker
    "74": "fg_0_39",
    "77": "fg_40_49",
    "80": "fg_50_plus",
    "85": "pat_made",
    # DST
    "99":  "dst_sack",
    "100": "dst_interception",
    "101": "dst_fumble_recovery",
    "102": "dst_td",
    "103": "dst_safety",
}

ESPN_POS_MAP = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "DST"}


# ── ESPN Fantasy API ──────────────────────────────────────────────────────────

@st.cache_data(ttl=43200)  # Cache 12 hrs — projections update daily
def fetch_espn_projections(season: int = ESPN_SEASON, scoring: str = "PPR") -> pd.DataFrame:
    """
    Pulls current-season player projections from ESPN's undocumented Fantasy API.
    Returns a DataFrame with name, position, team, stats (dict).

    NOTE: This is an unofficial endpoint. ESPN may change it without notice.
    The tool falls back to ADP-only rankings if this fails.
    """
    url = f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{season}/players"

    # X-Fantasy-Filter tells ESPN which stats and how many players to return.
    # statSourceId 1 = projections (0 = actuals)
    # statSplitTypeId 0 = full season total
    xff = json.dumps({
        "players": {
            "limit": 1000,
            "filterStatsForSourceIds":    {"value": [1]},
            "filterStatsForSplitTypeIds": {"value": [0]},
            "sortDraftRanks": {
                "sortPriority": 100,
                "sortAsc": True,
                "value": scoring.upper(),
            },
        }
    })

    headers = {
        "X-Fantasy-Filter": xff,
        "User-Agent": "Mozilla/5.0 (compatible; fantasy-draft-tool)",
        "Accept": "application/json",
    }
    params = {"scoringPeriodId": 0, "view": "kona_player_info"}

    try:
        resp = requests.get(url, headers=headers, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        st.warning(f"ESPN projections unavailable ({e}). Using ADP-only rankings.")
        return pd.DataFrame()

    # ESPN can return a dict with a "players" key, or occasionally a raw list
    if isinstance(data, list):
        player_list = data
    elif isinstance(data, dict):
        player_list = data.get("players", [])
    else:
        st.warning("ESPN returned an unexpected format. Using ADP-only rankings.")
        return pd.DataFrame()

    records = []
    for entry in player_list:
        pool   = entry.get("playerPoolEntry", {})
        player = pool.get("player", {})

        name   = player.get("fullName", "").strip()
        pos_id = player.get("defaultPositionId", 0)
        pos    = ESPN_POS_MAP.get(pos_id)
        team   = str(entry.get("onTeamId", ""))

        if not name or not pos:
            continue

        # Extract projected stat line from stats array
        stats = {}
        for stat_block in player.get("stats", []):
            # statSourceId 1 = projections, statSplitTypeId 0 = full season
            if stat_block.get("statSourceId") == 1 and stat_block.get("statSplitTypeId") == 0:
                raw = stat_block.get("stats", {})
                for espn_id, our_name in ESPN_STAT_MAP.items():
                    val = raw.get(espn_id, raw.get(int(espn_id), None))
                    if val is not None and float(val) != 0:
                        stats[our_name] = float(val)

        records.append({
            "espn_name": name,
            "position":  pos,
            "espn_team": team,
            "stats":     stats,
            "has_proj":  len(stats) > 0,
        })

    df = pd.DataFrame(records)
    matched = int(df["has_proj"].sum()) if not df.empty else 0
    if matched > 0:
        st.caption(f"📊 ESPN projections loaded: {matched} players with stat lines.")
    else:
        st.warning("ESPN returned data but no stat projections found. May be off-season.")

    return df


def merge_espn_onto_sleeper(sleeper_df: pd.DataFrame, espn_df: pd.DataFrame) -> pd.DataFrame:
    """
    Fuzzy-matches ESPN player names onto the Sleeper player list and
    attaches stat dicts.
    """
    if espn_df.empty:
        return sleeper_df

    updated      = sleeper_df.copy()
    sleeper_names = sleeper_df["name"].tolist()
    matched_count = 0

    for _, row in espn_df.iterrows():
        if not row["stats"]:
            continue
        result = fuzzy_process.extractOne(row["espn_name"], sleeper_names)
        if result and result[1] >= 85:
            match_name = result[0]
            mask = updated["name"] == match_name
            # Only update if position matches (avoids wrong-player matches)
            if updated.loc[mask, "position"].eq(row["position"]).any():
                updated.loc[mask, "stats"]             = [row["stats"]] * mask.sum()
                updated.loc[mask, "projection_source"] = f"ESPN {ESPN_SEASON}"
                matched_count += 1

    st.caption(f"✅ Matched {matched_count} players with ESPN {ESPN_SEASON} projections.")
    return updated


# ── Sleeper ADP ───────────────────────────────────────────────────────────────

@st.cache_data(ttl=3600)
def fetch_sleeper_adp() -> pd.DataFrame:
    """Pulls current player pool + ADP from Sleeper's free API."""
    url = "https://api.sleeper.app/v1/players/nfl"
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        players = resp.json()
    except Exception as e:
        st.warning(f"Could not fetch Sleeper data: {e}.")
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


# ── FantasyPros CSV upload handler ────────────────────────────────────────────

# FantasyPros exports use different column names — map them to our internal names
FANTASYPROS_COL_MAP = {
    "player":     "player_name",
    "fpts":       None,           # ignore — we calculate our own
    "g":          None,
    "pass_att":   "pass_attempts",
    "pass_comp":  "completions",
    "pass_yds":   "passing_yards",
    "pass_tds":   "passing_tds",
    "pass_ints":  "interceptions",
    "rush_att":   "rushing_attempts",
    "rush_yds":   "rushing_yards",
    "rush_tds":   "rushing_tds",
    "rec":        "receptions",
    "rec_yds":    "receiving_yards",
    "rec_tds":    "receiving_tds",
    "fl":         "fumbles_lost",
    # Kicker
    "fg":         "fg_total",
    "fga":        None,
    "xpt":        "pat_made",
}


def parse_user_upload(uploaded_file, master_df: pd.DataFrame) -> pd.DataFrame:
    """
    Parse a user-uploaded CSV. Handles both:
      - Our standard template format (player_name column)
      - FantasyPros export format (Player column, different stat names)
    """
    try:
        upload_df = pd.read_csv(uploaded_file)
    except Exception as e:
        st.error(f"Could not read file: {e}")
        return master_df

    # Normalize column names
    upload_df.columns = [c.strip().lower().replace(" ", "_") for c in upload_df.columns]

    # Detect and remap FantasyPros format
    is_fantasypros = "player" in upload_df.columns and "player_name" not in upload_df.columns
    if is_fantasypros:
        rename = {k: v for k, v in FANTASYPROS_COL_MAP.items() if k in upload_df.columns and v}
        drop   = [k for k, v in FANTASYPROS_COL_MAP.items() if k in upload_df.columns and v is None]
        upload_df = upload_df.rename(columns=rename).drop(columns=drop, errors="ignore")
        st.info("Detected FantasyPros format — column names remapped automatically.")

    if "player_name" not in upload_df.columns:
        st.error("Upload must have a 'player_name' (or 'Player' for FantasyPros exports) column.")
        return master_df

    # Remove team/position suffix that FantasyPros sometimes appends to names
    # e.g. "Patrick Mahomes KC QB" → "Patrick Mahomes"
    upload_df["player_name"] = upload_df["player_name"].str.replace(
        r"\s+[A-Z]{2,3}\s+(?:QB|RB|WR|TE|K|DST)$", "", regex=True
    ).str.strip()

    master_names  = master_df["name"].tolist()
    matched       = []
    unmatched     = []

    for idx, row in upload_df.iterrows():
        result = fuzzy_process.extractOne(str(row["player_name"]), master_names)
        if result and result[1] >= 85:
            pid = master_df[master_df["name"] == result[0]]["player_id"].iloc[0]
            matched.append((idx, pid))
        else:
            unmatched.append(row["player_name"])

    if unmatched:
        st.warning(f"Could not match {len(unmatched)} player(s): {', '.join(str(n) for n in unmatched[:10])}")

    updated_df = master_df.copy()
    skip_cols  = {"player_name", "player", "position", "team", "g", "fpts"}
    stat_cols  = [c for c in upload_df.columns if c not in skip_cols]

    for row_idx, pid in matched:
        row   = upload_df.iloc[row_idx]
        stats = {}
        for col in stat_cols:
            try:
                val = float(row[col])
                if not pd.isna(val):
                    stats[col] = val
            except (ValueError, TypeError):
                pass
        mask = updated_df["player_id"] == pid
        updated_df.loc[mask, "stats"]             = [stats] * mask.sum()
        updated_df.loc[mask, "projection_source"] = "user upload"

    st.success(f"Matched {len(matched)} players from upload.")
    return updated_df


# ── Master loader ─────────────────────────────────────────────────────────────

def load_players(scoring_type: str = "ppr") -> pd.DataFrame:
    """
    Main entry point.
    1. Load Sleeper player pool + ADP
    2. Pull ESPN projections and merge onto player list
    3. Return fully initialized DataFrame
    """
    sleeper_df = fetch_sleeper_adp()
    if sleeper_df.empty:
        sleeper_df = _placeholder_players()

    sleeper_df["stats"]             = [{}] * len(sleeper_df)
    sleeper_df["projected_points"]  = 0.0
    sleeper_df["vor"]               = 0.0
    sleeper_df["projection_source"] = "ADP only"
    sleeper_df["drafted"]           = False

    # Merge ESPN projections
    scoring_label = {"ppr": "PPR", "half_ppr": "HALF_PPR", "standard": "STANDARD"}.get(
        scoring_type, "PPR"
    )
    espn_df = fetch_espn_projections(season=ESPN_SEASON, scoring=scoring_label)
    if not espn_df.empty:
        sleeper_df = merge_espn_onto_sleeper(sleeper_df, espn_df)

    return sleeper_df.reset_index(drop=True)


def _placeholder_players() -> pd.DataFrame:
    data = [
        ("p001", "Patrick Mahomes",    "QB",  "KC",   2.1),
        ("p002", "Josh Allen",          "QB",  "BUF",  4.3),
        ("p003", "CeeDee Lamb",         "WR",  "DAL",  5.2),
        ("p004", "Tyreek Hill",         "WR",  "MIA",  7.8),
        ("p005", "Christian McCaffrey", "RB",  "SF",   1.1),
        ("p006", "Breece Hall",         "RB",  "NYJ",  9.4),
        ("p007", "Travis Kelce",        "TE",  "KC",  11.2),
        ("p008", "Sam LaPorta",         "TE",  "DET", 28.3),
        ("p009", "Justin Jefferson",    "WR",  "MIN",  3.4),
        ("p010", "Derrick Henry",       "RB",  "BAL", 14.2),
    ]
    return pd.DataFrame(data, columns=["player_id", "name", "position", "team", "adp"])
