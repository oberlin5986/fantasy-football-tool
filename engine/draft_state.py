"""
engine/draft_state.py
---------------------
Manages all mutable state during a live draft or simulation.

Uses a history stack so that undo is always O(1) — just pop the last snapshot.
Every pick (human or CPU) pushes a full state snapshot onto the stack.
"""

import copy
import random
import pandas as pd
from typing import Optional


class DraftState:
    def __init__(self, players_df: pd.DataFrame, league_config: dict):
        self.league_config   = league_config
        self.num_teams       = league_config["num_teams"]
        self.user_pick_pos   = league_config["draft_position"]  # 1-indexed
        self.total_rounds    = league_config["total_rounds"]
        self.draft_type      = league_config.get("draft_type", "snake")

        # Immutable source of truth — never modified
        self._source_df = players_df.copy()

        # History stack — each entry is a full snapshot of mutable state
        self._history = []

        # Initialize first state
        self._state = self._initial_state()

    # ── Public state accessors ────────────────────────────────────────────────

    @property
    def available_players(self) -> pd.DataFrame:
        ids = self._state["drafted_ids"]
        return self._source_df[~self._source_df["player_id"].isin(ids)].copy()

    @property
    def drafted_players(self) -> list:
        return self._state["pick_log"]

    @property
    def rosters(self) -> dict:
        """Returns dict of team_number → list of player dicts."""
        return self._state["rosters"]

    @property
    def current_pick_number(self) -> int:
        return self._state["current_pick"]

    @property
    def current_round(self) -> int:
        return ((self.current_pick_number - 1) // self.num_teams) + 1

    @property
    def current_team(self) -> int:
        """Which team (1-indexed) is on the clock."""
        pick = self.current_pick_number
        round_num = self.current_round
        pick_in_round = (pick - 1) % self.num_teams

        if self.draft_type == "snake" and round_num % 2 == 0:
            return self.num_teams - pick_in_round
        return pick_in_round + 1

    @property
    def is_user_turn(self) -> bool:
        return self.current_team == self.user_pick_pos

    @property
    def can_undo(self) -> bool:
        return len(self._history) > 0

    @property
    def draft_complete(self) -> bool:
        return self.current_pick_number > self.num_teams * self.total_rounds

    # ── Draft actions ─────────────────────────────────────────────────────────

    def make_pick(self, player_id: str, team: Optional[int] = None) -> dict:
        """
        Draft a player. team defaults to current_team.
        Returns the pick log entry.
        Pushes current state onto history stack before mutating.
        """
        team = team or self.current_team
        player = self._source_df[self._source_df["player_id"] == player_id].iloc[0]

        # Snapshot before mutation
        self._history.append(copy.deepcopy(self._state))

        # Mutate state
        pick_entry = {
            "pick_number": self.current_pick_number,
            "round":       self.current_round,
            "team":        team,
            "player_id":   player_id,
            "player_name": player["name"],
            "position":    player["position"],
            "is_user_pick": team == self.user_pick_pos,
        }

        self._state["drafted_ids"].add(player_id)
        self._state["pick_log"].append(pick_entry)
        self._state["rosters"][team].append(pick_entry)
        self._state["current_pick"] += 1

        return pick_entry

    def undo(self) -> Optional[dict]:
        """
        Revert the last pick. Returns the undone pick entry, or None if nothing to undo.
        """
        if not self._history:
            return None
        last_pick = self._state["pick_log"][-1] if self._state["pick_log"] else None
        self._state = self._history.pop()
        return last_pick

    def reset(self):
        """Reset to pre-draft state."""
        self._history.clear()
        self._state = self._initial_state()

    # ── Simulation ────────────────────────────────────────────────────────────

    def simulate_pick(self, variance: str = "medium") -> dict:
        """
        Auto-generate a CPU pick based on ADP + roster need + variance.
        Returns the pick entry after making it.
        """
        available = self.available_players
        team      = self.current_team
        roster    = self._state["rosters"][team]

        # Apply roster need weights
        pos_counts = {}
        for p in roster:
            pos_counts[p["position"]] = pos_counts.get(p["position"], 0) + 1

        # Penalize positions the team already has too many of
        def need_weight(pos):
            count = pos_counts.get(pos, 0)
            if count >= 4:   return 0.2
            if count >= 3:   return 0.6
            return 1.0

        available = available.copy()
        available["need_weight"] = available["position"].apply(need_weight)

        # Sort by ADP (lower = higher priority), apply need weight as a soft filter
        available = available.sort_values("adp").head(30)  # consider top 30 by ADP

        # Apply variance — how far from the top we might pick
        variance_map = {"low": 3, "medium": 8, "high": 20}
        pool_size    = variance_map.get(variance, 8)
        pool         = available.head(pool_size)
        pool         = pool[pool["need_weight"] > 0.2]

        if pool.empty:
            pool = available.head(5)

        chosen = pool.sample(1).iloc[0]
        return self.make_pick(chosen["player_id"], team=team)

    # ── Recommendations ───────────────────────────────────────────────────────

    def get_recommendations(self, top_n: int = 5) -> pd.DataFrame:
        """
        Returns top N recommended players for the user's current pick,
        ranked by VOR adjusted for roster need and positional scarcity.
        """
        available = self.available_players
        roster    = self._state["rosters"].get(self.user_pick_pos, [])

        pos_counts = {}
        for p in roster:
            pos_counts[p["position"]] = pos_counts.get(p["position"], 0) + 1

        # Boost score if position is a roster need
        slots = self.league_config["roster_slots"]
        def need_boost(pos):
            needed = slots.get(pos.lower(), 0)
            have   = pos_counts.get(pos, 0)
            if have < needed:
                return 1.2  # 20% boost for unfilled starters
            return 1.0

        available = available.copy()
        available["rec_score"] = (
            available["vor"] * available["position"].apply(need_boost)
        )

        return (
            available
            .sort_values("rec_score", ascending=False)
            .head(top_n)
            [["name", "position", "team", "projected_points", "vor", "adp", "rec_score"]]
        )

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _initial_state(self) -> dict:
        return {
            "current_pick": 1,
            "drafted_ids":  set(),
            "pick_log":     [],
            "rosters":      {i: [] for i in range(1, self.num_teams + 1)},
        }
