"""
engine/matchups.py
------------------
Identifies favorable matchups in weeks 1-3 (hot start) and 15-17 (playoffs).

Data sources:
  - NFL schedule: nflverse schedules.csv (updated when 2026 schedule releases ~May)
  - Defensive rankings: computed from nflverse 2025 weekly stats
    (how many fantasy points each team allowed per game by position)

Output per player:
  hot_start_score    float 0-1  avg matchup quality weeks 1-3
  playoff_score      float 0-1  avg matchup quality weeks 15-17
  hot_start_label    str  "Favorable" | "Neutral" | "Tough"
  playoff_label      str  "Favorable" | "Neutral" | "Tough"
  hot_start_weeks    list of {week, opponent, rank, label}
  playoff_weeks      list of {week, opponent, rank, label}
"""

import requests
import pandas as pd
import numpy as np
import io
from typing import Optional

NFLVERSE_SCHEDULES_URL = (
    "https://github.com/nflverse/nflverse-data/releases/download/schedules/schedules.csv"
)

CURRENT_SEASON = 2026
HOT_START_WEEKS = [1, 2, 3]
PLAYOFF_WEEKS   = [15, 16, 17]


# ── Schedule fetching ─────────────────────────────────────────────────────────

def fetch_schedule(season: int = CURRENT_SEASON) -> pd.DataFrame:
    """
    Downloads the NFL schedule from nflverse.
    Returns a DataFrame with columns: season, week, home_team, away_team.
    Falls back to empty DataFrame if unavailable (pre-schedule-release).
    """
    try:
        resp = requests.get(NFLVERSE_SCHEDULES_URL, timeout=20)
        resp.raise_for_status()
        df = pd.read_csv(io.StringIO(resp.text), low_memory=False)
        df = df[df["season"] == season][["season", "week", "home_team", "away_team"]]
        return df.dropna(subset=["week", "home_team", "away_team"])
    except Exception:
        return pd.DataFrame()


def get_team_opponent_map(schedule_df: pd.DataFrame) -> dict:
    """
    Returns a dict: {team: {week: opponent}}
    so you can quickly look up who any team plays in any week.
    """
    opponent_map = {}
    for _, row in schedule_df.iterrows():
        week  = int(row["week"])
        home  = str(row["home_team"]).upper()
        away  = str(row["away_team"]).upper()
        opponent_map.setdefault(home, {})[week] = away
        opponent_map.setdefault(away, {})[week] = home
    return opponent_map


# ── Defensive rankings ────────────────────────────────────────────────────────

def build_defensive_rankings(
    weekly_df: pd.DataFrame,
    scoring: dict,
    season: int = 2025,
) -> dict:
    """
    Computes how many fantasy points each NFL team allowed per game
    to each offensive position, using nflverse weekly data.

    Returns: {position: {team: avg_pts_allowed_per_game}}
    Higher = more fantasy-friendly (weaker defense against that position).
    """
    from engine.scoring import calculate_projected_points

    if weekly_df.empty:
        return {}

    df = weekly_df[weekly_df["season"] == season].copy()
    if df.empty:
        df = weekly_df.copy()

    # We need opponent info — nflverse weekly has recent_team (player's team)
    # and opponent (the opposing team) for each game
    if "opponent_team" not in df.columns and "recent_team" not in df.columns:
        return {}

    team_col = "recent_team" if "recent_team" in df.columns else "posteam"
    opp_col  = "opponent_team" if "opponent_team" in df.columns else "defteam"

    if opp_col not in df.columns:
        return {}

    positions = ["QB", "RB", "WR", "TE"]
    result    = {}

    for pos in positions:
        pos_df = df[df["position"] == pos].copy()
        if pos_df.empty:
            continue

        # Compute fantasy points for each player-game
        def game_pts(row):
            stats = {
                "passing_yards":   float(row.get("passing_yards",   0) or 0),
                "passing_tds":     float(row.get("passing_tds",     0) or 0),
                "interceptions":   float(row.get("interceptions",   0) or 0),
                "rushing_yards":   float(row.get("rushing_yards",   0) or 0),
                "rushing_tds":     float(row.get("rushing_tds",     0) or 0),
                "receptions":      float(row.get("receptions",      0) or 0),
                "receiving_yards": float(row.get("receiving_yards", 0) or 0),
                "receiving_tds":   float(row.get("receiving_tds",   0) or 0),
            }
            return calculate_projected_points(stats, scoring)

        pos_df["game_pts"] = pos_df.apply(game_pts, axis=1)

        # Group by opponent — how many points did that defense allow per game?
        def_avg = (
            pos_df.groupby(opp_col)["game_pts"]
            .mean()
            .to_dict()
        )
        result[pos] = def_avg

    return result


def rank_defenses(def_rankings: dict) -> dict:
    """
    Converts raw points-allowed averages into ranks 1-32.
    Rank 1 = most points allowed (best matchup for offense).
    Rank 32 = fewest points allowed (worst matchup).

    Returns: {position: {team: rank_1_to_32}}
    """
    ranked = {}
    for pos, team_avg in def_rankings.items():
        if not team_avg:
            continue
        sorted_teams = sorted(team_avg.items(), key=lambda x: x[1], reverse=True)
        ranked[pos] = {team: rank + 1 for rank, (team, _) in enumerate(sorted_teams)}
    return ranked


# ── Matchup scoring ───────────────────────────────────────────────────────────

def matchup_label(rank: int, total: int = 32) -> tuple:
    """
    Returns (label, icon) based on defensive rank.
    rank 1-10: favorable, 11-22: neutral, 23-32: tough
    """
    if rank <= 10:
        return "Favorable", "🟢"
    elif rank <= 22:
        return "Neutral",   "🟡"
    else:
        return "Tough",     "🔴"


def matchup_score_from_rank(rank: int, total: int = 32) -> float:
    """Convert rank to 0-1 score. Rank 1 → 1.0, Rank 32 → 0.0"""
    return round(1.0 - (rank - 1) / (total - 1), 3)


def calculate_player_matchups(
    team: str,
    position: str,
    opponent_map: dict,
    ranked_defenses: dict,
    weeks_to_check: list,
) -> list:
    """
    Returns a list of matchup dicts for the specified weeks.
    Each dict: {week, opponent, rank, score, label, icon}
    """
    results   = []
    pos_ranks = ranked_defenses.get(position, {})
    team_sched = opponent_map.get(team.upper(), {})

    for week in weeks_to_check:
        opponent = team_sched.get(week)
        if not opponent:
            results.append({
                "week": week, "opponent": "TBD",
                "rank": 16, "score": 0.5,
                "label": "Unknown", "icon": "⬜"
            })
            continue

        rank    = pos_ranks.get(opponent, 16)
        score   = matchup_score_from_rank(rank)
        label, icon = matchup_label(rank)
        results.append({
            "week":     week,
            "opponent": opponent,
            "rank":     rank,
            "score":    score,
            "label":    label,
            "icon":     icon,
        })

    return results


def aggregate_matchup_score(matchup_weeks: list) -> tuple:
    """Returns (avg_score, label, icon) for a set of matchup weeks."""
    if not matchup_weeks:
        return 0.5, "Unknown", "⬜"
    avg = np.mean([m["score"] for m in matchup_weeks])
    label, icon = matchup_label(round((1.0 - avg) * 31 + 1))
    return round(float(avg), 3), label, icon


# ── Apply to full DataFrame ───────────────────────────────────────────────────

def apply_matchups_to_df(
    df: pd.DataFrame,
    opponent_map: dict,
    ranked_defenses: dict,
) -> pd.DataFrame:
    """
    Adds matchup columns to the player DataFrame.
    Skips gracefully if schedule or defensive data is unavailable.
    """
    if not opponent_map or not ranked_defenses:
        # No schedule data — add empty columns so rest of code doesn't break
        df = df.copy()
        df["hot_start_score"] = 0.5
        df["hot_start_label"] = "Unknown"
        df["hot_start_icon"]  = "⬜"
        df["playoff_score"]   = 0.5
        df["playoff_label"]   = "Unknown"
        df["playoff_icon"]    = "⬜"
        df["hot_start_weeks"] = [[] for _ in range(len(df))]
        df["playoff_weeks"]   = [[] for _ in range(len(df))]
        return df

    df = df.copy()

    hot_scores, hot_labels, hot_icons = [], [], []
    po_scores,  po_labels,  po_icons  = [], [], []
    hot_weeks_list = []
    po_weeks_list  = []

    # Only calculate for skill positions (K/DST matchups work differently)
    skill_positions = {"QB", "RB", "WR", "TE"}

    for _, row in df.iterrows():
        pos  = row["position"]
        team = str(row["team"]).upper()

        if pos in skill_positions:
            hot_wks = calculate_player_matchups(
                team, pos, opponent_map, ranked_defenses, HOT_START_WEEKS
            )
            po_wks = calculate_player_matchups(
                team, pos, opponent_map, ranked_defenses, PLAYOFF_WEEKS
            )
        else:
            hot_wks = []
            po_wks  = []

        h_score, h_label, h_icon = aggregate_matchup_score(hot_wks)
        p_score, p_label, p_icon = aggregate_matchup_score(po_wks)

        hot_scores.append(h_score)
        hot_labels.append(h_label)
        hot_icons.append(h_icon)
        po_scores.append(p_score)
        po_labels.append(p_label)
        po_icons.append(p_icon)
        hot_weeks_list.append(hot_wks)
        po_weeks_list.append(po_wks)

    df["hot_start_score"] = hot_scores
    df["hot_start_label"] = hot_labels
    df["hot_start_icon"]  = hot_icons
    df["playoff_score"]   = po_scores
    df["playoff_label"]   = po_labels
    df["playoff_icon"]    = po_icons
    df["hot_start_weeks"] = hot_weeks_list
    df["playoff_weeks"]   = po_weeks_list

    return df
