"""
engine/vorp.py
--------------
Calculates Value Over Replacement (VOR) and positional scarcity.

When no stat projections exist, falls back to ADP-rank-based pseudo-VOR
so rankings are always meaningful even with ADP-only data.
"""

import pandas as pd
import numpy as np


def get_baseline_counts(league_config: dict) -> dict:
    """
    How many startable players exist at each position across the whole league.
    This determines who the replacement-level baseline player is.
    """
    n     = league_config["num_teams"]
    slots = league_config["roster_slots"]

    rb_flex = round(slots.get("flex", 1) * 0.5)
    wr_flex = round(slots.get("flex", 1) * 0.4)
    te_flex = round(slots.get("flex", 1) * 0.1)
    sf_qb   = slots.get("superflex", 0)

    return {
        "QB":  n * (slots.get("qb", 1) + sf_qb),
        "RB":  n * (slots.get("rb", 2) + rb_flex),
        "WR":  n * (slots.get("wr", 2) + wr_flex),
        "TE":  n * (slots.get("te", 1) + te_flex),
        "K":   n * max(slots.get("k", 1), 1),
        "DST": n * max(slots.get("dst", 1), 1),
    }


def calculate_vor(df: pd.DataFrame, league_config: dict) -> pd.DataFrame:
    """
    Adds a `vor` column to the DataFrame.

    If the player has real stat projections (projected_points > 0),
    VOR = projected_points − baseline projected_points at that position.

    If no projections exist (projected_points == 0 for all), falls back to
    an ADP-based pseudo-VOR so the board still ranks sensibly.
    """
    df = df.copy()
    baseline_counts = get_baseline_counts(league_config)

    has_projections = (df["projected_points"] > 0).any()

    if has_projections:
        # Standard VOR from projected points
        baselines = {}
        for pos, count in baseline_counts.items():
            pos_players = (
                df[df["position"] == pos]
                .sort_values("projected_points", ascending=False)
                .reset_index(drop=True)
            )
            if len(pos_players) > count:
                baselines[pos] = pos_players.iloc[count]["projected_points"]
            elif len(pos_players) > 0:
                baselines[pos] = pos_players.iloc[-1]["projected_points"]
            else:
                baselines[pos] = 0.0

        def _vor(row):
            return round(row["projected_points"] - baselines.get(row["position"], 0.0), 2)

        df["vor"]          = df.apply(_vor, axis=1)
        df["baseline_pts"] = df["position"].map(baselines)

    else:
        # ADP fallback: invert ADP rank within each position group
        # so lower ADP (better pick) = higher pseudo-VOR
        vor_values = []
        for pos, group in df.groupby("position"):
            baseline  = baseline_counts.get(pos, 12)
            group     = group.copy().sort_values("adp")
            ranks     = range(1, len(group) + 1)
            group["vor"] = [max(baseline - r, -20) for r in ranks]
            vor_values.append(group)

        df = pd.concat(vor_values) if vor_values else df
        df["baseline_pts"] = 0.0

    return df.reset_index(drop=True)


def get_scarcity_scores(available_df: pd.DataFrame, baseline_counts: dict) -> dict:
    """
    Returns a scarcity score per position: ratio of remaining players
    to total baseline starters. Lower = scarcer.

    Uses available_df (already filtered to undrafted players).
    Works whether or not VOR is populated.
    """
    scarcity = {}
    for pos, count in baseline_counts.items():
        remaining = len(available_df[available_df["position"] == pos])
        scarcity[pos] = round(remaining / max(count, 1), 2)
    return scarcity
