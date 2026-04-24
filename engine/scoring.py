"""
engine/scoring.py
-----------------
Converts raw per-player stat projections into fantasy points
based on the user's league scoring settings.

All calculation happens here — projected_points is NEVER stored
in player data, always computed fresh from stat lines + settings.
"""

from dataclasses import dataclass, field
from typing import Optional
import pandas as pd


# ── Default scoring settings (standard) ──────────────────────────────────────

DEFAULT_SCORING = {
    # Passing
    "passing_yards_per_point": 25,   # 1 pt per 25 yds
    "passing_td": 4.0,
    "interception": -2.0,
    "passing_2pt": 2.0,

    # Rushing
    "rushing_yards_per_point": 10,   # 1 pt per 10 yds
    "rushing_td": 6.0,
    "rushing_2pt": 2.0,

    # Receiving
    "reception": 0.0,                # 0 standard | 0.5 half-PPR | 1.0 PPR
    "receiving_yards_per_point": 10,
    "receiving_td": 6.0,
    "receiving_2pt": 2.0,

    # Misc
    "fumble_lost": -2.0,

    # Kicker
    "fg_0_39": 3.0,
    "fg_40_49": 4.0,
    "fg_50_plus": 5.0,
    "pat_made": 1.0,
    "pat_missed": -1.0,
    "fg_missed": -1.0,

    # DST
    "dst_sack": 1.0,
    "dst_interception": 2.0,
    "dst_fumble_recovery": 2.0,
    "dst_td": 6.0,
    "dst_safety": 2.0,
    "dst_points_allowed_0": 10.0,
    "dst_points_allowed_1_6": 7.0,
    "dst_points_allowed_7_13": 4.0,
    "dst_points_allowed_14_20": 1.0,
    "dst_points_allowed_21_27": 0.0,
    "dst_points_allowed_28_34": -1.0,
    "dst_points_allowed_35_plus": -4.0,
}

SCORING_PRESETS = {
    "Standard": {**DEFAULT_SCORING, "reception": 0.0},
    "Half-PPR":  {**DEFAULT_SCORING, "reception": 0.5},
    "PPR":       {**DEFAULT_SCORING, "reception": 1.0},
}


# ── Scoring calculation ───────────────────────────────────────────────────────

def calculate_projected_points(stats: dict, scoring: dict) -> float:
    """
    Given a player's projected stat line (dict) and a scoring settings dict,
    return total projected fantasy points.
    """
    pts = 0.0
    s = scoring  # shorthand

    # Passing
    pts += stats.get("passing_yards", 0) / s.get("passing_yards_per_point", 25)
    pts += stats.get("passing_tds", 0)   * s.get("passing_td", 4.0)
    pts += stats.get("interceptions", 0) * s.get("interception", -2.0)

    # Rushing
    pts += stats.get("rushing_yards", 0) / s.get("rushing_yards_per_point", 10)
    pts += stats.get("rushing_tds", 0)   * s.get("rushing_td", 6.0)

    # Receiving
    pts += stats.get("receptions", 0)      * s.get("reception", 0.0)
    pts += stats.get("receiving_yards", 0) / s.get("receiving_yards_per_point", 10)
    pts += stats.get("receiving_tds", 0)   * s.get("receiving_td", 6.0)

    # Fumbles
    pts += stats.get("fumbles_lost", 0) * s.get("fumble_lost", -2.0)

    # Kicker
    pts += stats.get("fg_0_39", 0)   * s.get("fg_0_39", 3.0)
    pts += stats.get("fg_40_49", 0)  * s.get("fg_40_49", 4.0)
    pts += stats.get("fg_50_plus", 0) * s.get("fg_50_plus", 5.0)
    pts += stats.get("pat_made", 0)  * s.get("pat_made", 1.0)

    # DST (simplified — points allowed bucket passed as string key)
    for key in [k for k in stats if k.startswith("dst_")]:
        if key in s:
            pts += stats[key] * s[key]

    return round(pts, 2)


def apply_scoring_to_df(df: pd.DataFrame, scoring: dict) -> pd.DataFrame:
    """
    Takes the full players DataFrame and adds/updates a `projected_points`
    column by applying the provided scoring settings to each player's stats.
    """
    df = df.copy()
    df["projected_points"] = df["stats"].apply(
        lambda stats: calculate_projected_points(stats if isinstance(stats, dict) else {}, scoring)
    )
    return df
