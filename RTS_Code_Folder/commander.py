"""
commander.py — Adaptive AI fleet commander.

Plays the strategic role the human player fills for their own team: decides
when the fleet breaks from holding at spawn and commits to a push, and how
hard to press the attack. It reads the same aggregate stats the per-ship
combat AI already publishes each frame (AICharacter.team_strength_ratio)
plus the live position of the enemy fleet, so its calls shift as the match
state shifts — pressing an advantage, advancing cautiously when even, or
pulling back to regroup when outmatched — without needing to know anything
about *how* the player is playing, only the result of it.

Ship-level tactics (target selection, flanking, retreat-at-low-HP, firing)
are unaffected — this only sets the fleet-wide rally point that idle
("patrol") leaders steer toward once deployed.
"""
import math
from entities import AICharacter


class AICommander:
    DECISION_INTERVAL = 1.0    # seconds between strategy re-evaluations
    OPENING_TIMEOUT    = 35.0  # force a push if neither side has engaged by then
    AGGRO_FRACTION     = 0.40  # enemy within this fraction of world width from our spawn triggers us

    def __init__(self, team: int, enemy_team: int,
                 own_spawn: tuple[float, float], enemy_spawn: tuple[float, float],
                 world_w: float, world_h: float):
        self.team        = team
        self.enemy_team  = enemy_team
        self.own_spawn   = own_spawn
        self.enemy_spawn = enemy_spawn
        self.world_w     = world_w
        self.world_h     = world_h

        self.deployed    = False   # whole-fleet "move out" order, issued once
        self.rally       = own_spawn
        self._elapsed    = 0.0
        self._decision_t = 0.0

    def update(self, dt: float, ai_characters: list) -> None:
        """Call once per frame. Re-evaluates strategy on a slower cadence
        (cheap aggregate scan) and applies the current rally order every frame."""
        self._elapsed += dt
        self._decision_t -= dt
        if self._decision_t <= 0.0:
            self._decision_t = self.DECISION_INTERVAL
            self._decide(ai_characters)
        self._apply(ai_characters)

    # ── Strategy ─────────────────────────────────────────────────────────────
    def _decide(self, ai_characters: list) -> None:
        own   = [s for s in ai_characters if s.alive and s.team == self.team]
        enemy = [s for s in ai_characters if s.alive and s.team == self.enemy_team]
        if not own:
            return

        enemy_centroid = self._centroid(enemy)
        own_centroid    = self._centroid(own) or self.own_spawn

        if not self.deployed:
            triggered = self._elapsed > self.OPENING_TIMEOUT
            if not triggered and enemy_centroid is not None:
                trigger_dist = self.AGGRO_FRACTION * self.world_w
                d = math.hypot(enemy_centroid[0] - self.own_spawn[0],
                                enemy_centroid[1] - self.own_spawn[1])
                triggered = d < trigger_dist
            if triggered:
                self.deployed = True
                for s in own:
                    s.deployed = True

        if not self.deployed:
            self.rally = self.own_spawn
            return

        # No enemy in sight yet — probe toward their last known territory.
        push_target = enemy_centroid if enemy_centroid is not None else self.enemy_spawn

        # Adaptive aggression: press hard while winning, advance cautiously
        # while even, and pull back toward spawn to regroup while losing
        # badly — reading the fight's outcome rather than guessing intent.
        ratio = AICharacter.team_strength_ratio.get(self.team, 1.0)
        if ratio > 1.15:
            push_frac = 0.95
        elif ratio < 0.45:
            push_frac = 0.10
        elif ratio < 0.75:
            push_frac = 0.35
        else:
            push_frac = 0.60

        rx = own_centroid[0] + (push_target[0] - own_centroid[0]) * push_frac
        ry = own_centroid[1] + (push_target[1] - own_centroid[1]) * push_frac
        self.rally = (rx, ry)

    @staticmethod
    def _centroid(ships: list):
        if not ships:
            return None
        sx = sum(s.wx + s.width / 2 for s in ships)
        sy = sum(s.wy + s.height / 2 for s in ships)
        return (sx / len(ships), sy / len(ships))

    # ── Execution ────────────────────────────────────────────────────────────
    def _apply(self, ai_characters: list) -> None:
        if not self.deployed:
            return
        for s in ai_characters:
            if not s.alive or s.team != self.team:
                continue
            is_fleet_leader = s.fleet_leader is None or s.fleet_leader is s
            if is_fleet_leader and s.combat_state == 'patrol':
                s._movement_override = self.rally
