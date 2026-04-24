"""
engine/variance.py
------------------
Boom / Bust / Balanced / Steady variance profiling.

Calibration philosophy:
  - WITHOUT projections: most players should be Balanced, with cold-outdoor
    players or clear positional extremes (goal-line backs, deep TEs) drifting
    toward Boom/Bust. Dome high-usage players drift toward Steady.
  - WITH projections: td_pct is the dominant driver. Players over 40% TD
    share clearly Boom/Bust. High-volume PPR producers are Balanced or Steady.

Thresholds:
  Steady    < 0.30   🟢  Reliable floor week-to-week
  Balanced  0.30–0.52 🟡  Mix of floor and upside
  Boom/Bust > 0.52   🔴  High ceiling, low floor
"""

import pandas as pd
import numpy as np
from typing import Optional

# ── Stadium environments ──────────────────────────────────────────────────────
TEAM_ENVIRONMENT = {
    "NO":  "dome",        "DET": "dome",        "MIN": "dome",
    "IND": "dome",        "SEA": "dome",
    "KC":  "retractable", "LAR": "retractable",  "LAC": "retractable",
    "LV":  "retractable", "DAL": "retractable",  "ARI": "retractable",
    "ATL": "retractable", "HOU": "retractable",
    "MIA": "outdoor_warm","TB":  "outdoor_warm", "JAX": "outdoor_warm",
    "SF":  "outdoor_warm","TEN": "outdoor_warm", "CAR": "outdoor_warm",
    "BUF": "outdoor_cold","GB":  "outdoor_cold", "CHI": "outdoor_cold",
    "NE":  "outdoor_cold","PIT": "outdoor_cold", "CLE": "outdoor_cold",
    "CIN": "outdoor_cold","NYG": "outdoor_cold", "NYJ": "outdoor_cold",
    "PHI": "outdoor_cold","WAS": "outdoor_cold", "BAL": "outdoor_cold",
    "DEN": "outdoor_cold",
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

# ── Position variance bases (no-projection defaults) ─────────────────────────
# Lower than before — most players should be Balanced without projection data.
# Only extreme env (cold outdoor) or extreme positions push to Boom/Bust.
POSITION_VARIANCE_BASE = {
    "QB":  0.18,
    "RB":  0.27,
    "WR":  0.30,
    "TE":  0.34,
    "K":   0.28,
    "DST": 0.32,
}

POSITION_NO_PROJ_BONUS = {
    "QB":  0.04,
    "RB":  0.07,
    "WR":  0.08,
    "TE":  0.10,
    "K":   0.06,
    "DST": 0.08,
}

BOOM_BUST_THRESHOLD = 0.52
STEADY_THRESHOLD    = 0.30


def get_environment(team: str) -> str:
    return TEAM_ENVIRONMENT.get(str(team).upper(), "outdoor_warm")


def calculate_variance_score(
    stats: dict,
    projected_points: float,
    position: str,
    team: str,
    scoring: dict,
    historical_std: Optional[float] = None,
    schedule_env_var: Optional[float] = None,  # overrides static env when schedule is available
) -> dict:
    """Returns full variance profile dict for a single player."""

    env     = get_environment(team)
    # Use schedule-adjusted environment if available (accounts for home/away mix)
    env_var = schedule_env_var if schedule_env_var is not None else ENVIRONMENT_VARIANCE.get(env, 0.10)
    env_bonus = env_var * 0.5

    pos_base = POSITION_VARIANCE_BASE.get(position, 0.30)

    # ── No projections ────────────────────────────────────────────────────────
    if projected_points <= 0:
        no_proj_bonus = POSITION_NO_PROJ_BONUS.get(position, 0.08)
        if historical_std is not None:
            hist_norm = min(historical_std / 18.0, 1.0)
            score = pos_base + hist_norm * 0.25 + env_bonus
        else:
            score = pos_base + no_proj_bonus + env_bonus
        score = round(min(score, 1.0), 3)
        return _build_result(score, 0.0, 0.0, env, env_var, historical_std)

    # ── Projection-based ─────────────────────────────────────────────────────
    td_pts  = 0.0
    td_pts += stats.get("passing_tds",   0) * scoring.get("passing_td",  4.0)
    td_pts += stats.get("rushing_tds",   0) * scoring.get("rushing_td",  6.0)
    td_pts += stats.get("receiving_tds", 0) * scoring.get("receiving_td", 6.0)
    td_pct  = min(td_pts / projected_points, 1.0)

    floor_pts  = 0.0
    floor_pts += stats.get("passing_yards",   0) / scoring.get("passing_yards_per_point",   25)
    floor_pts += stats.get("rushing_yards",   0) / scoring.get("rushing_yards_per_point",   10)
    floor_pts += stats.get("receiving_yards", 0) / scoring.get("receiving_yards_per_point", 10)
    floor_pts += stats.get("receptions",      0) * scoring.get("reception", 0.0)
    floor_pct  = min(floor_pts / projected_points, 1.0)

    # TD dependency: kicks in above 25% TD share, scales to Boom/Bust territory
    td_bonus      = max(0.0, td_pct - 0.25) * 1.6

    # Anti-floor: rewards players who lack a consistent yardage/reception base
    anti_floor    = max(0.0, 0.60 - floor_pct) * 0.40

    score = pos_base + td_bonus + anti_floor + env_bonus

    if historical_std is not None:
        hist_norm = min(historical_std / 18.0, 1.0)
        # Historical std blends in at 15% weight
        score = score * 0.85 + hist_norm * 0.28 * 0.15

    score = round(min(max(score, 0.0), 1.0), 3)
    return _build_result(score, td_pct, floor_pct, env, env_var, historical_std)


def _build_result(score, td_pct, floor_pct, env, env_var, hist_std):
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
        "env_var":        round(env_var, 3),
        "historical_std": hist_std,
    }


def apply_variance_to_df(
    df: pd.DataFrame,
    scoring: dict,
    weekly_std_map: Optional[dict] = None,
    schedule_env_map: Optional[dict] = None,  # {player_id: avg_env_var} if available
) -> pd.DataFrame:
    df = df.copy()

    v_scores, v_labels, v_icons = [], [], []
    td_pcts, floor_pcts, envs, env_lbls, env_vars = [], [], [], [], []

    for _, row in df.iterrows():
        hist_std    = weekly_std_map.get(row["name"]) if weekly_std_map else None
        sched_env   = schedule_env_map.get(row["player_id"]) if schedule_env_map else None

        result = calculate_variance_score(
            stats             = row["stats"] if isinstance(row["stats"], dict) else {},
            projected_points  = float(row.get("projected_points", 0)),
            position          = row["position"],
            team              = row["team"],
            scoring           = scoring,
            historical_std    = hist_std,
            schedule_env_var  = sched_env,
        )
        v_scores.append(result["variance_score"])
        v_labels.append(result["variance_label"])
        v_icons.append(result["variance_icon"])
        td_pcts.append(result["td_pct"])
        floor_pcts.append(result["floor_pct"])
        envs.append(result["environment"])
        env_lbls.append(result["env_label"])
        env_vars.append(result["env_var"])

    df["variance_score"] = v_scores
    df["variance_label"] = v_labels
    df["variance_icon"]  = v_icons
    df["td_pct"]         = td_pcts
    df["floor_pct"]      = floor_pcts
    df["environment"]    = envs
    df["env_label"]      = env_lbls
    df["env_var"]        = env_vars
    return df


def get_roster_variance_profile(roster_picks: list, players_df: pd.DataFrame) -> dict:
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
    elif avg_score > 0.52:
        rec = "🔴 Boom/bust lean — one steady pick balances things."
    elif avg_score < 0.30:
        rec = "🟢 Very steady roster — affordable to take a boom/bust swing."
    else:
        rec = "✅ Well-balanced variance profile — draft best available."

    return {"counts": counts, "avg_score": round(avg_score, 3), "recommendation": rec}


def build_weekly_std_map(weekly_df: pd.DataFrame, scoring: dict) -> dict:
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
            weekly_pts.append(calculate_projected_points(stats, scoring))
        if len(weekly_pts) >= 4:
            std_map[name] = round(float(np.std(weekly_pts)), 2)
    return std_map
