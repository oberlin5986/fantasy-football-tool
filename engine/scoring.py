"""
engine/scoring.py
-----------------
Converts raw per-player stat projections into fantasy points.
projected_points is NEVER stored — always computed fresh from stat lines + settings.
"""

import pandas as pd

# ── Default scoring settings ──────────────────────────────────────────────────
DEFAULT_SCORING = {
    # Passing
    "passing_yards_per_point":  25,     # 1 pt per 25 yds
    "passing_td":               4.0,
    "interception":            -2.0,
    "completion_bonus":         0.0,    # pts per completion (most leagues: 0)
    "passing_attempt_bonus":    0.0,    # pts per pass attempt (rare)
    "passing_2pt":              2.0,

    # Rushing
    "rushing_yards_per_point":  10,     # 1 pt per 10 yds
    "rushing_td":               6.0,
    "rushing_attempt_bonus":    0.0,    # pts per rushing attempt (rare)
    "rushing_2pt":              2.0,
    "bonus_rush_100":           0.0,    # bonus pts for 100+ rush yard game
    "bonus_rush_200":           0.0,    # bonus pts for 200+ rush yard game

    # Receiving
    "reception":                0.0,    # 0 standard | 0.5 half-PPR | 1.0 PPR
    "receiving_yards_per_point": 10,
    "receiving_td":             6.0,
    "target_bonus":             0.0,    # pts per target (rare)
    "receiving_2pt":            2.0,
    "bonus_rec_100":            0.0,    # bonus pts for 100+ receiving yard game
    "bonus_rec_200":            0.0,

    # Passing bonuses
    "bonus_pass_300":           0.0,    # bonus for 300+ passing yard game
    "bonus_pass_400":           0.0,

    # Misc
    "fumble_lost":             -2.0,

    # Kicker
    "fg_0_39":                  3.0,
    "fg_40_49":                 4.0,
    "fg_50_plus":               5.0,
    "pat_made":                 1.0,
    "pat_missed":              -1.0,
    "fg_missed":               -1.0,

    # DST
    "dst_sack":                 1.0,
    "dst_interception":         2.0,
    "dst_fumble_recovery":      2.0,
    "dst_td":                   6.0,
    "dst_safety":               2.0,
    "dst_points_allowed_0":     10.0,
    "dst_points_allowed_1_6":   7.0,
    "dst_points_allowed_7_13":  4.0,
    "dst_points_allowed_14_20": 1.0,
    "dst_points_allowed_21_27": 0.0,
    "dst_points_allowed_28_34":-1.0,
    "dst_points_allowed_35_plus": -4.0,
}

SCORING_PRESETS = {
    "Standard": {**DEFAULT_SCORING, "reception": 0.0},
    "Half-PPR":  {**DEFAULT_SCORING, "reception": 0.5},
    "PPR":       {**DEFAULT_SCORING, "reception": 1.0},
}


def calculate_projected_points(stats: dict, scoring: dict) -> float:
    """
    Convert a player's projected stat line into fantasy points
    using the provided scoring settings dict.
    """
    if not stats:
        return 0.0

    pts = 0.0
    s   = scoring

    # Passing
    pts += stats.get("passing_yards", 0)    / s.get("passing_yards_per_point", 25)
    pts += stats.get("passing_tds", 0)      * s.get("passing_td", 4.0)
    pts += stats.get("interceptions", 0)    * s.get("interception", -2.0)
    pts += stats.get("completions", 0)      * s.get("completion_bonus", 0.0)
    pts += stats.get("pass_attempts", 0)    * s.get("passing_attempt_bonus", 0.0)

    pass_yds = stats.get("passing_yards", 0)
    if pass_yds >= 400:
        pts += s.get("bonus_pass_400", 0.0)
    elif pass_yds >= 300:
        pts += s.get("bonus_pass_300", 0.0)

    # Rushing
    pts += stats.get("rushing_yards", 0)    / s.get("rushing_yards_per_point", 10)
    pts += stats.get("rushing_tds", 0)      * s.get("rushing_td", 6.0)
    pts += stats.get("rushing_attempts", 0) * s.get("rushing_attempt_bonus", 0.0)

    rush_yds = stats.get("rushing_yards", 0)
    if rush_yds >= 200:
        pts += s.get("bonus_rush_200", 0.0)
    elif rush_yds >= 100:
        pts += s.get("bonus_rush_100", 0.0)

    # Receiving
    pts += stats.get("receptions", 0)       * s.get("reception", 0.0)
    pts += stats.get("receiving_yards", 0)  / s.get("receiving_yards_per_point", 10)
    pts += stats.get("receiving_tds", 0)    * s.get("receiving_td", 6.0)
    pts += stats.get("targets", 0)          * s.get("target_bonus", 0.0)

    rec_yds = stats.get("receiving_yards", 0)
    if rec_yds >= 200:
        pts += s.get("bonus_rec_200", 0.0)
    elif rec_yds >= 100:
        pts += s.get("bonus_rec_100", 0.0)

    # Misc
    pts += stats.get("fumbles_lost", 0)     * s.get("fumble_lost", -2.0)

    # Kicker
    pts += stats.get("fg_0_39", 0)          * s.get("fg_0_39", 3.0)
    pts += stats.get("fg_40_49", 0)         * s.get("fg_40_49", 4.0)
    pts += stats.get("fg_50_plus", 0)       * s.get("fg_50_plus", 5.0)
    pts += stats.get("pat_made", 0)         * s.get("pat_made", 1.0)
    pts += stats.get("pat_missed", 0)       * s.get("pat_missed", -1.0)
    pts += stats.get("fg_missed", 0)        * s.get("fg_missed", -1.0)

    # DST
    for key in [k for k in stats if k.startswith("dst_")]:
        if key in s:
            pts += stats[key] * s[key]

    return round(pts, 2)


def apply_scoring_to_df(df: pd.DataFrame, scoring: dict) -> pd.DataFrame:
    """Adds/updates projected_points column using each player's stats dict."""
    df = df.copy()
    df["projected_points"] = df["stats"].apply(
        lambda st: calculate_projected_points(st if isinstance(st, dict) else {}, scoring)
    )
    return df
