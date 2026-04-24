"""
engine/variance.py
------------------
Calculates boom/bust/steady profiles for each player based on:
  1. TD dependency ratio      — how much of projected value comes from TDs
  2. Volume floor score       — how much comes from reliable yards/receptions
  3. Stadium environment      — dome vs outdoor vs cold-weather outdoor
  4. Historical std deviation — actual week-to-week variance from last season
     (populated when nflverse weekly data is available)

Output per player:
  variance_score  float 0.0–1.0  (higher = more volatile)
  variance_label  "Boom/Bust" | "Balanced" | "Steady"
  variance_icon   "🔴" | "🟡" | "🟢"
  td_pct          float — share of projected points from TDs
  floor_pct       float — share from non-TD yards/receptions
  environment     str   — dome | retractable | outdoor_warm | outdoor_cold
"""

import pandas as pd
import numpy as np
from typing import Optional

# ── Stadium environment ───────────────────────────────────────────────────────
# Dome / retractable / outdoor warm / outdoor cold
# Updated for 2026 rosters

TEAM_ENVIRONMENT = {
    # Full domes
    "NO":  "dome",
    "DET": "dome",
    "MIN": "dome",
    "IND": "dome",
    "HOU": "dome",   # NRG Stadium has retractable but almost always closed
    "SEA": "dome",   # Lumen Field — covered but open-air counts as dome-like
    # Retractable roofs (mostly closed for games)
    "KC":  "retractable",
    "LAR": "retractable",
    "LAC": "retractable",
    "LV":  "retractable",
    "DAL": "retractable",
    "ARI": "retractable",
    "ATL": "retractable",
    # Outdoor warm-weather (mild temps, low wind/rain variance)
    "MIA": "outdoor_warm",
    "TB":  "outdoor_warm",
    "JAX": "outdoor_warm",
    "LAX": "outdoor_warm",  # fallback
    # Outdoor cold-weather (meaningful late-season variance)
    "BUF": "outdoor_cold",
    "GB":  "outdoor_cold",
    "CHI": "outdoor_cold",
    "NE":  "outdoor_cold",
    "PIT": "outdoor_cold",
    "CLE": "outdoor_cold",
    "CIN": "outdoor_cold",
    "NYG": "outdoor_cold",
    "NYJ": "outdoor_cold",
    "PHI": "outdoor_cold",
    "WAS": "outdoor_cold",
    "BAL": "outdoor_cold",
    "DEN": "outdoor_cold",
    # Default outdoor (moderate)
    "SF":  "outdoor_warm",
    "TEN": "outdoor_warm",
    "CAR": "outdoor_warm",
    "NO2": "outdoor_warm",
}

ENVIRONMENT_VARIANCE = {
    "dome":          0.00,
    "retractable":   0.05,
    "outdoor_warm":  0.10,
    "outdoor_cold":  0.22,
}

ENVIRONMENT_LABELS = {
    "dome":          "🏟️ Dome",
    "retractable":   "🏟️ Retractable",
    "outdoor_warm":  "☀️ Outdoor",
    "outdoor_cold":  "❄️ Cold/Outdoor",
}


def get_environment(team: str) -> str:
    return TEAM_ENVIRONMENT.get(str(team).upper(), "outdoor_warm")


# ── Core variance calculation ─────────────────────────────────────────────────

def calculate_variance_score(
    stats: dict,
    projected_points: float,
    position: str,
    team: str,
    scoring: dict,
    historical_std: Optional[float] = None,
) -> dict:
    """
    Returns a full variance profile for a single player.

    Parameters
    ----------
    stats              : projected stat line dict
    projected_points   : total projected fantasy points (pre-calculated)
    position           : QB / RB / WR / TE / K / DST
    team               : NFL team abbreviation
    scoring            : league scoring settings dict
    historical_std     : optional — observed weekly std dev from last season
    """

    if projected_points <= 0:
        # No projections — use position-based defaults
        defaults = {
            "QB":  {"variance_score": 0.35, "label": "Balanced"},
            "RB":  {"variance_score": 0.45, "label": "Balanced"},
            "WR":  {"variance_score": 0.50, "label": "Balanced"},
            "TE":  {"variance_score": 0.55, "label": "Boom/Bust"},
            "K":   {"variance_score": 0.40, "label": "Balanced"},
            "DST": {"variance_score": 0.45, "label": "Balanced"},
        }
        d = defaults.get(position, {"variance_score": 0.45, "label": "Balanced"})
        env = get_environment(team)
        env_var = ENVIRONMENT_VARIANCE.get(env, 0.10)
        score = min(d["variance_score"] + env_var * 0.5, 1.0)
        return _build_result(score, 0.0, 0.0, env, historical_std)

    # ── TD points ────────────────────────────────────────────────────────────
    td_points = 0.0
    td_points += stats.get("passing_tds", 0)   * scoring.get("passing_td", 4.0)
    td_points += stats.get("rushing_tds", 0)   * scoring.get("rushing_td", 6.0)
    td_points += stats.get("receiving_tds", 0) * scoring.get("receiving_td", 6.0)

    td_pct = min(td_points / projected_points, 1.0) if projected_points > 0 else 0.0

    # ── Volume floor points (non-TD yards + receptions) ──────────────────────
    floor_points = 0.0
    floor_points += (stats.get("passing_yards", 0) / scoring.get("passing_yards_per_point", 25))
    floor_points += (stats.get("rushing_yards", 0)  / scoring.get("rushing_yards_per_point", 10))
    floor_points += (stats.get("receiving_yards", 0) / scoring.get("receiving_yards_per_point", 10))
    floor_points += stats.get("receptions", 0) * scoring.get("reception", 0.0)

    floor_pct = min(floor_points / projected_points, 1.0) if projected_points > 0 else 0.0

    # ── Environment variance ──────────────────────────────────────────────────
    env = get_environment(team)
    env_var = ENVIRONMENT_VARIANCE.get(env, 0.10)

    # ── Composite score ───────────────────────────────────────────────────────
    # Weights: TD dependency 40%, volume floor (inverted) 30%, environment 15%,
    # historical std 15% (if available)
    td_component    = td_pct * 0.40
    floor_component = (1.0 - floor_pct) * 0.30
    env_component   = env_var * 0.15

    if historical_std is not None:
        # Normalize historical std to 0-1 range (std > 20 = max variance)
        hist_norm       = min(historical_std / 20.0, 1.0)
        hist_component  = hist_norm * 0.15
        # Rescale other components to sum to 0.85
        variance_score  = (td_component + floor_component + env_component) * (0.85 / 0.85) + hist_component
    else:
        # Without historical data, rescale to use full weight
        variance_score = (td_component + floor_component + env_component) / 0.85

    variance_score = round(min(max(variance_score, 0.0), 1.0), 3)

    return _build_result(variance_score, td_pct, floor_pct, env, historical_std)


def _build_result(score, td_pct, floor_pct, env, hist_std):
    if score < 0.30:
        label, icon = "Steady",    "🟢"
    elif score < 0.55:
        label, icon = "Balanced",  "🟡"
    else:
        label, icon = "Boom/Bust", "🔴"

    return {
        "variance_score": score,
        "variance_label": label,
        "variance_icon":  icon,
        "td_pct":         round(td_pct, 3),
        "floor_pct":      round(floor_pct, 3),
        "environment":    env,
        "env_label":      ENVIRONMENT_LABELS.get(env, ""),
        "historical_std": hist_std,
    }


# ── Apply to full DataFrame ───────────────────────────────────────────────────

def apply_variance_to_df(df: pd.DataFrame, scoring: dict,
                          weekly_std_map: Optional[dict] = None) -> pd.DataFrame:
    """
    Adds variance columns to the full player DataFrame.

    weekly_std_map: optional dict of {player_name: float} from historical data
    """
    df = df.copy()

    variance_scores  = []
    variance_labels  = []
    variance_icons   = []
    td_pcts          = []
    floor_pcts       = []
    environments     = []
    env_labels       = []

    for _, row in df.iterrows():
        hist_std = None
        if weekly_std_map:
            hist_std = weekly_std_map.get(row["name"])

        result = calculate_variance_score(
            stats            = row["stats"] if isinstance(row["stats"], dict) else {},
            projected_points = float(row.get("projected_points", 0)),
            position         = row["position"],
            team             = row["team"],
            scoring          = scoring,
            historical_std   = hist_std,
        )

        variance_scores.append(result["variance_score"])
        variance_labels.append(result["variance_label"])
        variance_icons.append(result["variance_icon"])
        td_pcts.append(result["td_pct"])
        floor_pcts.append(result["floor_pct"])
        environments.append(result["environment"])
        env_labels.append(result["env_label"])

    df["variance_score"] = variance_scores
    df["variance_label"] = variance_labels
    df["variance_icon"]  = variance_icons
    df["td_pct"]         = td_pcts
    df["floor_pct"]      = floor_pcts
    df["environment"]    = environments
    df["env_label"]      = env_labels

    return df


# ── Roster variance profile ───────────────────────────────────────────────────

def get_roster_variance_profile(roster_picks: list, players_df: pd.DataFrame) -> dict:
    """
    Given a list of pick dicts from the draft state, returns a variance
    profile for the user's current roster.

    Returns:
      counts       : {"Boom/Bust": N, "Balanced": N, "Steady": N}
      avg_score    : float — average variance score across roster
      recommendation : str — advice on what profile to target next
    """
    if not roster_picks or "variance_label" not in players_df.columns:
        return {"counts": {}, "avg_score": 0.5, "recommendation": ""}

    drafted_ids = {p["player_id"] for p in roster_picks}
    roster_df   = players_df[players_df["player_id"].isin(drafted_ids)]

    counts = roster_df["variance_label"].value_counts().to_dict()
    avg_score = float(roster_df["variance_score"].mean()) if len(roster_df) > 0 else 0.5

    boom  = counts.get("Boom/Bust", 0)
    bal   = counts.get("Balanced", 0)
    stead = counts.get("Steady", 0)
    total = boom + bal + stead

    if total == 0:
        rec = "Draft a few players to see your variance profile."
    elif boom / max(total, 1) > 0.6:
        rec = "Your roster is high-variance. Consider adding a steady floor player next."
    elif stead / max(total, 1) > 0.6:
        rec = "Your roster is floor-heavy. You have room to swing for upside."
    elif avg_score > 0.50:
        rec = "Slight boom/bust lean — one more steady pick balances the roster."
    elif avg_score < 0.35:
        rec = "Very steady roster — you can afford a boom/bust upside play."
    else:
        rec = "Well-balanced variance profile. Draft best available."

    return {
        "counts":         counts,
        "avg_score":      round(avg_score, 3),
        "recommendation": rec,
    }


# ── Historical std dev from nflverse weekly data ──────────────────────────────

def build_weekly_std_map(weekly_df: pd.DataFrame, scoring: dict) -> dict:
    """
    Given a DataFrame of weekly player stats (from nflverse),
    calculates per-player standard deviation in weekly fantasy points.

    Returns dict: {player_name: std_dev_float}
    """
    from engine.scoring import calculate_projected_points

    if weekly_df.empty:
        return {}

    std_map = {}

    for name, group in weekly_df.groupby("player_name"):
        weekly_pts = []
        for _, row in group.iterrows():
            stats = {
                "passing_yards":   row.get("passing_yards", 0) or 0,
                "passing_tds":     row.get("passing_tds", 0) or 0,
                "interceptions":   row.get("interceptions", 0) or 0,
                "rushing_yards":   row.get("rushing_yards", 0) or 0,
                "rushing_tds":     row.get("rushing_tds", 0) or 0,
                "receptions":      row.get("receptions", 0) or 0,
                "receiving_yards": row.get("receiving_yards", 0) or 0,
                "receiving_tds":   row.get("receiving_tds", 0) or 0,
                "fumbles_lost":    row.get("rushing_fumbles_lost", 0) or 0,
            }
            pts = calculate_projected_points(stats, scoring)
            weekly_pts.append(pts)

        if len(weekly_pts) >= 4:  # need at least 4 games for meaningful std
            std_map[name] = round(float(np.std(weekly_pts)), 2)

    return std_map
