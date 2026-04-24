"""
engine/vorp.py
--------------
Calculates Value Over Replacement Player (VOR/VORP) for each player
based on league roster settings.

The baseline player at each position is the last "startable" player —
determined by the number of teams and roster slots.
"""

import pandas as pd


def get_baseline_counts(league_config: dict) -> dict:
    """
    Returns how many starters exist at each position given league settings.
    These determine who the 'baseline' (replacement-level) player is.

    Example: 12 teams, 2 RB slots, 1 FLEX (assume ~50% goes to RB)
    → ~30 startable RBs → baseline is RB30
    """
    n = league_config["num_teams"]
    slots = league_config["roster_slots"]

    rb_flex   = round(slots.get("flex", 1) * 0.5)
    wr_flex   = round(slots.get("flex", 1) * 0.4)
    te_flex   = round(slots.get("flex", 1) * 0.1)
    sf_qb     = slots.get("superflex", 0)   # superflex mostly adds QB value

    return {
        "QB": n * (slots.get("qb", 1) + sf_qb),
        "RB": n * (slots.get("rb", 2) + rb_flex),
        "WR": n * (slots.get("wr", 2) + wr_flex),
        "TE": n * (slots.get("te", 1) + te_flex),
        "K":  n * slots.get("k", 1),
        "DST": n * slots.get("dst", 1),
    }


def calculate_vor(df: pd.DataFrame, league_config: dict) -> pd.DataFrame:
    """
    Adds a `vor` column to the DataFrame.
    VOR = player projected_points − baseline player projected_points at position.
    Players with VOR > 0 are above replacement level.
    """
    df = df.copy()
    baseline_counts = get_baseline_counts(league_config)
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
        baseline = baselines.get(row["position"], 0.0)
        return round(row["projected_points"] - baseline, 2)

    df["vor"] = df.apply(_vor, axis=1)
    df["baseline_pts"] = df["position"].map(baselines)

    return df


def get_scarcity_scores(df: pd.DataFrame, baseline_counts: dict) -> dict:
    """
    Returns a scarcity score per position: how many viable (VOR > 0)
    players remain relative to baseline count. Lower = scarcer.

    Returns dict like: {"RB": 0.4, "WR": 0.8, "TE": 0.2, ...}
    """
    available = df[~df.get("drafted", pd.Series(False, index=df.index))]
    scarcity = {}

    for pos, count in baseline_counts.items():
        viable = available[
            (available["position"] == pos) & (available["vor"] > 0)
        ]
        scarcity[pos] = round(len(viable) / max(count, 1), 2)

    return scarcity
