"""
engine/variance.py
------------------
Boom / Bust / Steady / Balanced variance profiling.

Key design decisions:
  - Position variance base encodes known game-script dependency by position
  - TD dependency bonus heavily penalizes players relying on TDs for value
  - Anti-floor bonus rewards players with minimal reliable production
  - Environment modifier reflects dome vs outdoor/cold reality
  - Historical std dev (when available) anchors to actual observed data

Thresholds:
  Steady    < 0.30   🟢  Reliable floor, low weekly variance
  Balanced  0.30–0.48 🟡  Mix of floor and upside
  Boom/Bust > 0.48   🔴  High ceiling, low floor, TD-dependent or weather-exposed
"""

import pandas as pd
import numpy as np
from typing import Optional

# ── Stadium environments ──────────────────────────────────────────────────────
TEAM_ENVIRONMENT = {
    # Full domes
    "NO": "dome", "DET": "dome", "MIN": "dome",
    "IND": "dome", "SEA": "dome",
    # Retractable (almost always closed)
    "KC": "retractable", "LAR": "retractable", "LAC": "retractable",
    "LV": "retractable", "DAL": "retractable", "ARI": "retractable",
    "ATL": "retractable", "HOU": "retractable",
    # Outdoor warm
    "MIA": "outdoor_warm", "TB": "outdoor_warm", "JAX": "outdoor_warm",
    "SF":  "outdoor_warm", "TEN": "outdoor_warm", "CAR": "outdoor_warm",
    "NO2": "outdoor_warm",
    # Outdoor cold (meaningful late-season variance)
    "BUF": "outdoor_cold", "GB": "outdoor_cold", "CHI": "outdoor_cold",
    "NE":  "outdoor_cold", "PIT": "outdoor_cold", "CLE": "outdoor_cold",
    "CIN": "outdoor_cold", "NYG": "outdoor_cold", "NYJ": "outdoor_cold",
    "PHI": "outdoor_cold", "WAS": "outdoor_cold", "BAL": "outdoor_cold",
    "DEN": "outdoor_cold",
}

ENVIRONMENT_VARIANCE = {
    "dome":         0.00,
    "retractable":  0.05,
    "outdoor_warm": 0.10,
    "outdoor_cold": 0.22,
}

ENVIRONMENT_LABELS = {
    "dome":         "🏟️ Dome",
    "retractable":  "🏟️ Retractable",
    "outdoor_warm": "☀️ Outdoor",
    "outdoor_cold": "❄️ Cold/Outdoor",
}

# ── Position variance bases ───────────────────────────────────────────────────
# These encode the known inherent game-script dependency of each position.
# WRs and TEs have higher base variance because even high-volume players
# have feast-or-famine weekly outputs driven by targets and coverage.

POSITION_VARIANCE_BASE = {
    "QB":  0.20,   # Relatively predictable — volume stat producers
    "RB":  0.30,   # Committee/injury risk raises variance
    "WR":  0.40,   # Inherently game-script dependent
    "TE":  0.45,   # TD-dependent, few reliable starters outside top 3
    "K":   0.30,   # Moderate — driven by team scoring and opportunities
    "DST": 0.38,   # Matchup-driven, high week-to-week swings
}

# Additional no-projection bonus — reflects that unknown roles have extra risk
POSITION_NO_PROJ_BONUS = {
    "QB":  0.05,
    "RB":  0.10,
    "WR":  0.15,
    "TE":  0.20,
    "K":   0.08,
    "DST": 0.12,
}

BOOM_BUST_THRESHOLD = 0.48
STEADY_THRESHOLD    = 0.30


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
    """Returns full variance profile dict for a single player."""

    env        = get_environment(team)
    env_var    = ENVIRONMENT_VARIANCE.get(env, 0.10)
    pos_base   = POSITION_VARIANCE_BASE.get(position, 0.35)
    env_bonus  = env_var * 0.5

    # ── No projections path ───────────────────────────────────────────────────
    if projected_points <= 0:
        no_proj_bonus = POSITION_NO_PROJ_BONUS.get(position, 0.10)
        if historical_std is not None:
            # Historical std anchors the estimate even without projections
            hist_norm  = min(historical_std / 18.0, 1.0)
            score      = pos_base + hist_norm * 0.30 + env_bonus
        else:
            score = pos_base + no_proj_bonus + env_bonus
        score = round(min(score, 1.0), 3)
        return _build_result(score, 0.0, 0.0, env, historical_std)

    # ── Projection-based path ─────────────────────────────────────────────────
    # TD points
    td_pts  = 0.0
    td_pts += stats.get("passing_tds",   0) * scoring.get("passing_td",  4.0)
    td_pts += stats.get("rushing_tds",   0) * scoring.get("rushing_td",  6.0)
    td_pts += stats.get("receiving_tds", 0) * scoring.get("receiving_td", 6.0)
    td_pct  = min(td_pts / projected_points, 1.0)

    # Volume floor points (reliable non-TD production)
    floor_pts  = 0.0
    floor_pts += stats.get("passing_yards",   0) / scoring.get("passing_yards_per_point",   25)
    floor_pts += stats.get("rushing_yards",   0) / scoring.get("rushing_yards_per_point",   10)
    floor_pts += stats.get("receiving_yards", 0) / scoring.get("receiving_yards_per_point", 10)
    floor_pts += stats.get("receptions",      0) * scoring.get("reception", 0.0)
    floor_pct  = min(floor_pts / projected_points, 1.0)

    # TD dependency bonus — heavily penalizes players where TDs drive value
    # Kicks in above 20% TD share, scales sharply above 40%
    td_dependency_bonus = max(0.0, td_pct - 0.20) * 1.8

    # Anti-floor bonus — rewards players whose points aren't backed by volume
    anti_floor_bonus = max(0.0, 0.65 - floor_pct) * 0.50

    score = pos_base + td_dependency_bonus + anti_floor_bonus + env_bonus

    # Historical std modifies the final score (±15% weight)
    if historical_std is not None:
        hist_norm = min(historical_std / 18.0, 1.0)
        score = score * 0.85 + hist_norm * 0.30 * 0.15

    score = round(min(max(score, 0.0), 1.0), 3)
    return _build_result(score, td_pct, floor_pct, env, historical_std)


def _build_result(score, td_pct, floor_pct, env, hist_std):
    if score < STEADY_THRESHOLD:
        label, icon = "Steady",    "🟢"
    elif score < BOOM_BUST_THRESHOLD:
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

def apply_variance_to_df(
    df: pd.DataFrame,
    scoring: dict,
    weekly_std_map: Optional[dict] = None,
) -> pd.DataFrame:
    df = df.copy()

    v_scores, v_labels, v_icons = [], [], []
    td_pcts, floor_pcts, envs, env_lbls = [], [], [], []

    for _, row in df.iterrows():
        hist_std = weekly_std_map.get(row["name"]) if weekly_std_map else None
        result   = calculate_variance_score(
            stats            = row["stats"] if isinstance(row["stats"], dict) else {},
            projected_points = float(row.get("projected_points", 0)),
            position         = row["position"],
            team             = row["team"],
            scoring          = scoring,
            historical_std   = hist_std,
        )
        v_scores.append(result["variance_score"])
        v_labels.append(result["variance_label"])
        v_icons.append(result["variance_icon"])
        td_pcts.append(result["td_pct"])
        floor_pcts.append(result["floor_pct"])
        envs.append(result["environment"])
        env_lbls.append(result["env_label"])

    df["variance_score"] = v_scores
    df["variance_label"] = v_labels
    df["variance_icon"]  = v_icons
    df["td_pct"]         = td_pcts
    df["floor_pct"]      = floor_pcts
    df["environment"]    = envs
    df["env_label"]      = env_lbls
    return df


# ── Roster variance profile ───────────────────────────────────────────────────

def get_roster_variance_profile(
    roster_picks: list,
    players_df: pd.DataFrame,
) -> dict:
    if not roster_picks or "variance_label" not in players_df.columns:
        return {"counts": {}, "avg_score": 0.5, "recommendation": ""}

    drafted_ids = {p["player_id"] for p in roster_picks}
    roster_df   = players_df[players_df["player_id"].isin(drafted_ids)]

    counts    = roster_df["variance_label"].value_counts().to_dict()
    avg_score = float(roster_df["variance_score"].mean()) if len(roster_df) > 0 else 0.5

    boom  = counts.get("Boom/Bust", 0)
    bal   = counts.get("Balanced",  0)
    stead = counts.get("Steady",    0)
    total = max(boom + bal + stead, 1)

    if boom / total > 0.60:
        rec = "⚠️ High-variance roster — add a steady floor player next."
    elif stead / total > 0.60:
        rec = "🎯 Floor-heavy roster — room to swing for upside."
    elif avg_score > 0.48:
        rec = "🔴 Slight boom/bust lean — one steady pick balances things."
    elif avg_score < 0.30:
        rec = "🟢 Very steady roster — affordable to take a boom/bust swing."
    else:
        rec = "✅ Well-balanced variance profile — draft best available."

    return {
        "counts":         counts,
        "avg_score":      round(avg_score, 3),
        "recommendation": rec,
    }


# ── Historical std dev from nflverse weekly data ──────────────────────────────

def build_weekly_std_map(weekly_df: pd.DataFrame, scoring: dict) -> dict:
    """Calculates per-player weekly fantasy point std dev from nflverse data."""
    from engine.scoring import calculate_projected_points

    if weekly_df.empty:
        return {}

    std_map = {}
    for name, group in weekly_df.groupby("player_name"):
        weekly_pts = []
        for _, row in group.iterrows():
            stats = {
                "passing_yards":   float(row.get("passing_yards",   0) or 0),
                "passing_tds":     float(row.get("passing_tds",     0) or 0),
                "interceptions":   float(row.get("interceptions",   0) or 0),
                "rushing_yards":   float(row.get("rushing_yards",   0) or 0),
                "rushing_tds":     float(row.get("rushing_tds",     0) or 0),
                "rushing_attempts":float(row.get("carries",         0) or 0),
                "receptions":      float(row.get("receptions",      0) or 0),
                "receiving_yards": float(row.get("receiving_yards", 0) or 0),
                "receiving_tds":   float(row.get("receiving_tds",   0) or 0),
                "fumbles_lost":   (float(row.get("rushing_fumbles_lost",   0) or 0) +
                                   float(row.get("receiving_fumbles_lost", 0) or 0)),
            }
            pts = calculate_projected_points(stats, scoring)
            weekly_pts.append(pts)
        if len(weekly_pts) >= 4:
            std_map[name] = round(float(np.std(weekly_pts)), 2)

    return std_map
