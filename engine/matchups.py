"""
engine/matchups.py
------------------
Schedule-aware matchup scoring for weeks 1-3 (hot start) and 15-17 (playoffs).

Schedule sources tried in order:
  1. nflverse schedules for CURRENT_SEASON (2026)
  2. ESPN public schedule API  
  3. nflverse schedules for prior season (2025) used as a proxy
  4. If all fail: show "Schedule Pending" — clears automatically when available

Schedule-aware environment:
  Rather than using a team's static home stadium for all games, we look at
  the actual opponent for each specific week. Home games use the player's
  stadium; away games use the opponent's stadium. This correctly captures
  a cold-weather team playing multiple dome away games in a given stretch.
"""

import requests
import pandas as pd
import numpy as np
import io
import json
from typing import Optional

from engine.variance import TEAM_ENVIRONMENT, ENVIRONMENT_VARIANCE, ENVIRONMENT_LABELS

CURRENT_SEASON  = 2026
PRIOR_SEASON    = 2025
HOT_START_WEEKS = [1, 2, 3]
PLAYOFF_WEEKS   = [15, 16, 17]

SCHEDULE_URLS = [
    # nflverse current season
    f"https://github.com/nflverse/nflverse-data/releases/download/schedules/schedules.csv",
    # nflverse alternate path
    f"https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv",
]

TEAM_ABBR_MAP = {
    # ESPN sometimes uses different abbreviations
    "WSH": "WAS", "JAC": "JAX", "LAX": "LAC",
}


# ── Schedule fetching ─────────────────────────────────────────────────────────

def _normalize_team(t: str) -> str:
    t = str(t).upper().strip()
    return TEAM_ABBR_MAP.get(t, t)


def _parse_schedule_csv(text: str, season: int) -> pd.DataFrame:
    """Parse nflverse schedule CSV for a given season."""
    df = pd.read_csv(io.StringIO(text), low_memory=False)
    needed = ["season", "week", "home_team", "away_team"]
    if not all(c in df.columns for c in needed):
        return pd.DataFrame()
    df = df[df["season"] == season][needed].dropna()
    df["home_team"] = df["home_team"].apply(_normalize_team)
    df["away_team"] = df["away_team"].apply(_normalize_team)
    return df.reset_index(drop=True)


def fetch_schedule(season: int = CURRENT_SEASON) -> tuple:
    """
    Returns (schedule_df, is_proxy, proxy_note).

    schedule_df : DataFrame with season/week/home_team/away_team, or empty
    is_proxy    : True if using prior season as fallback
    proxy_note  : Human-readable note shown in UI
    """
    for url in SCHEDULE_URLS:
        try:
            resp = requests.get(url, timeout=20)
            if resp.status_code != 200:
                continue
            # Try current season
            df = _parse_schedule_csv(resp.text, season)
            if not df.empty:
                return df, False, ""
            # Try prior season as proxy
            df_prior = _parse_schedule_csv(resp.text, season - 1)
            if not df_prior.empty:
                note = (f"📅 Using {season-1} schedule as proxy — "
                        f"{season} schedule typically releases in May and will update automatically.")
                return df_prior, True, note
        except Exception:
            continue

    # All sources failed
    return pd.DataFrame(), False, "📅 Schedule not yet available — matchup data will appear once the NFL releases the schedule."


def get_team_opponent_map(schedule_df: pd.DataFrame) -> dict:
    """Returns {team: {week: opponent}} for home/away lookups."""
    opp_map = {}
    for _, row in schedule_df.iterrows():
        week = int(row["week"])
        home = str(row["home_team"]).upper()
        away = str(row["away_team"]).upper()
        opp_map.setdefault(home, {})[week] = ("home", away)
        opp_map.setdefault(away, {})[week] = ("away", home)
    return opp_map


# ── Schedule-aware environment ────────────────────────────────────────────────

def get_game_env_var(team: str, location: str, opponent: str) -> float:
    """
    Returns the environment variance for a single game.
    Home game → player's stadium environment.
    Away game → opponent's stadium environment.
    """
    if location == "home":
        env = TEAM_ENVIRONMENT.get(team.upper(), "outdoor_warm")
    else:
        env = TEAM_ENVIRONMENT.get(opponent.upper(), "outdoor_warm")
    return ENVIRONMENT_VARIANCE.get(env, 0.10)


def build_schedule_env_map(
    players_df: pd.DataFrame,
    opponent_map: dict,
    weeks: list,
) -> dict:
    """
    For each player, computes the average environment variance
    across the specified weeks based on their actual schedule.

    Returns: {player_id: avg_env_var}
    """
    env_map = {}
    for _, row in players_df.iterrows():
        team      = str(row["team"]).upper()
        pid       = row["player_id"]
        team_sched = opponent_map.get(team, {})

        game_envs = []
        for week in weeks:
            if week in team_sched:
                location, opponent = team_sched[week]
                game_envs.append(get_game_env_var(team, location, opponent))

        if game_envs:
            env_map[pid] = round(float(np.mean(game_envs)), 3)
        # If no schedule data, leave absent — variance.py falls back to static env

    return env_map


# ── Defensive rankings ────────────────────────────────────────────────────────

def build_defensive_rankings(weekly_df: pd.DataFrame, scoring: dict, season: int = PRIOR_SEASON) -> dict:
    """
    Computes avg fantasy points allowed per game per position per defending team.
    Returns: {position: {defending_team: avg_pts_allowed}}
    """
    from engine.scoring import calculate_projected_points

    if weekly_df.empty:
        return {}

    df = weekly_df.copy()
    if "season" in df.columns:
        season_df = df[df["season"] == season]
        df = season_df if not season_df.empty else df

    opp_col  = next((c for c in ["opponent_team", "defteam", "recent_opponent"] if c in df.columns), None)
    if opp_col is None:
        return {}

    positions = ["QB", "RB", "WR", "TE"]
    result    = {}

    for pos in positions:
        pos_df = df[df["position"] == pos].copy()
        if pos_df.empty:
            continue

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
        def_avg = pos_df.groupby(opp_col)["game_pts"].mean().to_dict()
        result[pos] = {_normalize_team(k): v for k, v in def_avg.items()}

    return result


def rank_defenses(def_rankings: dict) -> dict:
    """Rank 1 = most pts allowed (best matchup). Rank 32 = fewest."""
    ranked = {}
    for pos, team_avg in def_rankings.items():
        if not team_avg:
            continue
        sorted_teams = sorted(team_avg.items(), key=lambda x: x[1], reverse=True)
        ranked[pos]  = {team: rank + 1 for rank, (team, _) in enumerate(sorted_teams)}
    return ranked


# ── Per-player matchup calculation ────────────────────────────────────────────

def matchup_label_from_rank(rank: int, total: int = 32) -> tuple:
    if rank <= 10:  return "Favorable", "🟢"
    if rank <= 22:  return "Neutral",   "🟡"
    return              "Tough",     "🔴"


def matchup_score_from_rank(rank: int, total: int = 32) -> float:
    return round(1.0 - (rank - 1) / max(total - 1, 1), 3)


def calculate_player_matchups(team, position, opponent_map, ranked_defenses, weeks):
    results    = []
    pos_ranks  = ranked_defenses.get(position, {})
    team_sched = opponent_map.get(str(team).upper(), {})

    for week in weeks:
        if week not in team_sched:
            results.append({"week": week, "opponent": "TBD", "location": "?",
                             "rank": 16, "score": 0.5, "label": "Pending", "icon": "⬜"})
            continue

        location, opponent = team_sched[week]
        rank  = pos_ranks.get(opponent, 16)
        score = matchup_score_from_rank(rank)
        label, icon = matchup_label_from_rank(rank)
        results.append({
            "week": week, "opponent": opponent,
            "location": "🏠" if location == "home" else "✈️",
            "rank": rank, "score": score, "label": label, "icon": icon,
        })
    return results


def aggregate_matchup_score(matchup_weeks: list) -> tuple:
    if not matchup_weeks:
        return 0.5, "Pending", "⬜"
    real = [m for m in matchup_weeks if m["label"] != "Pending"]
    if not real:
        return 0.5, "Pending", "⬜"
    avg   = np.mean([m["score"] for m in real])
    label, icon = matchup_label_from_rank(round((1.0 - avg) * 31 + 1))
    return round(float(avg), 3), label, icon


# ── Apply to full DataFrame ───────────────────────────────────────────────────

def apply_matchups_to_df(
    df: pd.DataFrame,
    opponent_map: dict,
    ranked_defenses: dict,
    schedule_available: bool = False,
) -> pd.DataFrame:
    df = df.copy()

    hot_scores, hot_labels, hot_icons = [], [], []
    po_scores,  po_labels,  po_icons  = [], [], []
    hot_weeks_list, po_weeks_list     = [], []

    skill = {"QB", "RB", "WR", "TE"}

    for _, row in df.iterrows():
        pos  = row["position"]
        team = str(row["team"]).upper()

        if pos in skill and opponent_map:
            hw = calculate_player_matchups(team, pos, opponent_map, ranked_defenses, HOT_START_WEEKS)
            pw = calculate_player_matchups(team, pos, opponent_map, ranked_defenses, PLAYOFF_WEEKS)
        else:
            hw, pw = [], []

        hs, hl, hi = aggregate_matchup_score(hw)
        ps, pl, pi = aggregate_matchup_score(pw)

        hot_scores.append(hs); hot_labels.append(hl); hot_icons.append(hi)
        po_scores.append(ps);  po_labels.append(pl);  po_icons.append(pi)
        hot_weeks_list.append(hw)
        po_weeks_list.append(pw)

    df["hot_start_score"] = hot_scores
    df["hot_start_label"] = hot_labels
    df["hot_start_icon"]  = hot_icons
    df["playoff_score"]   = po_scores
    df["playoff_label"]   = po_labels
    df["playoff_icon"]    = po_icons
    df["hot_start_weeks"] = hot_weeks_list
    df["playoff_weeks"]   = po_weeks_list
    return df
