"""
engine/draft_state.py
---------------------
Manages all mutable state during a live draft or simulation.

Uses a history stack so that undo is always O(1) — just pop the last snapshot.
Every pick (human or CPU) pushes a full state snapshot onto the stack.
"""

import copy
import pandas as pd
from typing import Optional


POSITIONS = ["QB", "RB", "WR", "TE", "K", "DST"]


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
        """Returns dict of team_number -> list of player dicts."""
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
        pick          = self.current_pick_number
        round_num     = self.current_round
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
        Pushes current state onto history stack before mutating.
        """
        team   = team or self.current_team
        player = self._source_df[self._source_df["player_id"] == player_id].iloc[0]

        self._history.append(copy.deepcopy(self._state))

        pick_entry = {
            "pick_number":  self.current_pick_number,
            "round":        self.current_round,
            "team":         team,
            "player_id":    player_id,
            "player_name":  player["name"],
            "position":     player["position"],
            "is_user_pick": team == self.user_pick_pos,
        }

        self._state["drafted_ids"].add(player_id)
        self._state["pick_log"].append(pick_entry)
        self._state["rosters"][team].append(pick_entry)
        self._state["current_pick"] += 1

        return pick_entry

    def undo(self) -> Optional[dict]:
        """Revert the last pick. Returns the undone pick entry."""
        if not self._history:
            return None
        last_pick   = self._state["pick_log"][-1] if self._state["pick_log"] else None
        self._state = self._history.pop()
        return last_pick

    def reset(self):
        """Reset to pre-draft state."""
        self._history.clear()
        self._state = self._initial_state()

    # ── Simulation ────────────────────────────────────────────────────────────

    def simulate_pick(self, variance: str = "medium") -> dict:
        """CPU pick: ADP + roster need + variance."""
        available = self.available_players
        team      = self.current_team
        roster    = self._state["rosters"][team]

        pos_counts = {}
        for p in roster:
            pos_counts[p["position"]] = pos_counts.get(p["position"], 0) + 1

        def need_weight(pos):
            count = pos_counts.get(pos, 0)
            if count >= 4: return 0.2
            if count >= 3: return 0.6
            return 1.0

        available                = available.copy()
        available["need_weight"] = available["position"].apply(need_weight)
        available                = available.sort_values("adp").head(30)

        variance_map = {"low": 3, "medium": 8, "high": 20}
        pool_size    = variance_map.get(variance, 8)
        pool         = available.head(pool_size)
        pool         = pool[pool["need_weight"] > 0.2]

        if pool.empty:
            pool = available.head(5)

        chosen = pool.sample(1).iloc[0]
        return self.make_pick(chosen["player_id"], team=team)

    # ── Team composition ──────────────────────────────────────────────────────

    def get_all_team_summaries(self) -> dict:
        """
        Returns a summary of every team's roster composition.

        Output:
          { 1: { "picks": [...], "pos_counts": {"QB": 1, "RB": 2, ...} }, ... }
        """
        summaries = {}
        for team_num in range(1, self.num_teams + 1):
            picks      = self._state["rosters"].get(team_num, [])
            pos_counts = {}
            for p in picks:
                pos_counts[p["position"]] = pos_counts.get(p["position"], 0) + 1
            summaries[team_num] = {
                "picks":      picks,
                "pos_counts": pos_counts,
            }
        return summaries

    def get_teams_picking_before_me(self) -> list:
        """
        Returns list of team numbers that pick between now and the user's
        next pick, in order.
        """
        if self.draft_complete:
            return []

        teams_before = []
        pick = self.current_pick_number

        while True:
            round_num     = ((pick - 1) // self.num_teams) + 1
            pick_in_round = (pick - 1) % self.num_teams

            if self.draft_type == "snake" and round_num % 2 == 0:
                team = self.num_teams - pick_in_round
            else:
                team = pick_in_round + 1

            if team == self.user_pick_pos:
                break

            teams_before.append(team)
            pick += 1

            if pick > self.num_teams * self.total_rounds:
                break

        return teams_before

    def get_run_risk(self) -> dict:
        """
        For each position returns:
          run_active    - bool: 3+ of the last 5 picks were this position
          teams_needing - int: teams picking before user that still need this pos
          risk_level    - "high" | "medium" | "low"
        """
        log           = self._state["pick_log"]
        recent        = [p["position"] for p in log[-5:]] if log else []
        teams_before  = self.get_teams_picking_before_me()
        all_summaries = self.get_all_team_summaries()
        slots         = self.league_config["roster_slots"]

        results = {}
        for pos in POSITIONS:
            needed_slots = slots.get(pos.lower(), 1)

            run_active = recent.count(pos) >= 3

            teams_needing = 0
            for t in teams_before:
                have = all_summaries[t]["pos_counts"].get(pos, 0)
                if have < needed_slots:
                    teams_needing += 1

            if run_active or (len(teams_before) > 0 and
                              teams_needing >= max(2, len(teams_before) * 0.5)):
                risk = "high"
            elif teams_needing >= 1:
                risk = "medium"
            else:
                risk = "low"

            results[pos] = {
                "run_active":    run_active,
                "teams_needing": teams_needing,
                "picks_before":  len(teams_before),
                "risk_level":    risk,
            }

        return results

    # ── Recommendations ───────────────────────────────────────────────────────

    def get_recommendations(self, top_n: int = 5) -> list:
        """
        Returns top N recommended players as a list of dicts, with reasoning.
        Accounts for user roster needs, scarcity, and opponent compositions.
        """
        available     = self.available_players
        my_roster     = self._state["rosters"].get(self.user_pick_pos, [])
        run_risk      = self.get_run_risk()
        slots         = self.league_config["roster_slots"]

        my_pos_counts = {}
        for p in my_roster:
            my_pos_counts[p["position"]] = my_pos_counts.get(p["position"], 0) + 1

        def score_player(row):
            pos        = row["position"]
            vor        = row["vor"] if row["vor"] > 0 else 0.1
            risk_level = run_risk.get(pos, {}).get("risk_level", "low")
            needed     = slots.get(pos.lower(), 1)
            have       = my_pos_counts.get(pos, 0)
            need_mult  = 1.2 if have < needed else 1.0
            risk_mult  = {"high": 1.35, "medium": 1.15, "low": 1.0}.get(risk_level, 1.0)
            return vor * need_mult * risk_mult

        def build_reasoning(row):
            pos          = row["position"]
            risk_info    = run_risk.get(pos, {})
            risk_level   = risk_info.get("risk_level", "low")
            needed       = slots.get(pos.lower(), 1)
            have         = my_pos_counts.get(pos, 0)
            teams_need   = risk_info.get("teams_needing", 0)
            run_active   = risk_info.get("run_active", False)
            picks_before = risk_info.get("picks_before", 0)

            reasons = []

            if have < needed:
                reasons.append(f"Fills your {pos} need ({have}/{needed} starters)")
            elif have == needed:
                reasons.append(f"{pos} starter filled — adds depth")
            else:
                reasons.append(f"Already have {have} {pos}s — luxury pick")

            if run_active:
                reasons.append(f"Active {pos} run — act now")
            elif risk_level == "high" and teams_need > 0:
                reasons.append(f"{teams_need} team(s) ahead still need a {pos}")
            elif risk_level == "medium":
                reasons.append(f"Moderate {pos} demand from teams ahead")
            elif picks_before > 0:
                reasons.append(f"Low demand ahead — safe to wait if needed")
            else:
                reasons.append("You're on the clock")

            return " · ".join(reasons)

        available              = available.copy()
        available["rec_score"] = available.apply(score_player, axis=1)
        available["reasoning"] = available.apply(build_reasoning, axis=1)
        available["urgency"]   = available["position"].apply(
            lambda p: run_risk.get(p, {}).get("risk_level", "low")
        )

        top = available.sort_values("rec_score", ascending=False).head(top_n)

        return top[[
            "name", "position", "team", "projected_points",
            "vor", "adp", "rec_score", "reasoning", "urgency"
        ]].to_dict("records")

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _initial_state(self) -> dict:
        return {
            "current_pick": 1,
            "drafted_ids":  set(),
            "pick_log":     [],
            "rosters":      {i: [] for i in range(1, self.num_teams + 1)},
        }
