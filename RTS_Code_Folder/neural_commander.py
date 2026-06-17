"""
neural_commander.py — Neural-network fleet commander.

Same role as AICommander (commander.py): decide when the fleet commits to a
push and where each fleet should rally. Where AICommander uses one fixed
push-fraction lookup table for the whole team, NeuralCommander asks a small
trained network for a *per-fleet* push fraction and target choice every
decision tick.

The network is trained by imitation learning (see train_commander.py):
generate realistic game states from fast rule-based-vs-rule-based matches,
label each fleet's ideal (push fraction, target fleet) with a richer
per-fleet version of AICommander's own heuristic, and fit the network to
reproduce those labels via ordinary supervised learning. That trains in
minutes instead of the hours self-play reinforcement learning would need,
while still outputting genuine per-fleet tactics instead of one team-wide
rally point.

The observation is egocentric: features are always framed as "own" vs
"enemy", with world-x mirrored for team 1, so the same weights work for
either team. Fleets are identified by rank (strongest-HP-first), not by
identity, so the network doesn't need to track which specific carrier is
"fleet 0" across ticks.
"""
import os
import math

import torch
import torch.nn as nn

from entities import Carrier
from commander import AICommander

MAX_FLEETS = 4   # matches NUM_CARRIERS_PER_TEAM with the game's default NUM_AI=100

MODEL_PATH = os.path.join(os.path.dirname(__file__), 'models', 'commander_policy.pt')


class CommanderPolicy(nn.Module):
    """Small feed-forward net. See module docstring for the observation layout.

    Outputs, per own fleet slot: a push-fraction logit (sigmoid -> 0..1) and
    a distribution over which enemy fleet slot to rally toward.
    """

    GLOBAL_FEATS      = 8
    OWN_FLEET_FEATS   = 6
    ENEMY_FLEET_FEATS = 5
    ECONOMY_FEATS     = 6   # iron, copper, titanium, crystal, fuel (norm), miner count
    IN_DIM = (GLOBAL_FEATS + MAX_FLEETS * OWN_FLEET_FEATS
              + MAX_FLEETS * ENEMY_FLEET_FEATS + ECONOMY_FEATS)  # 58

    def __init__(self, hidden: int = 64):
        super().__init__()
        self.backbone = nn.Sequential(
            nn.Linear(self.IN_DIM, hidden), nn.Tanh(),
            nn.Linear(hidden, hidden),      nn.Tanh(),
        )
        self.push_logit     = nn.Linear(hidden, MAX_FLEETS)
        self.target_logits  = nn.Linear(hidden, MAX_FLEETS * MAX_FLEETS)

    def forward(self, obs: torch.Tensor):
        """obs: (batch, IN_DIM) -> push_logit (batch,F), target_logits (batch,F,F)"""
        h = self.backbone(obs)
        push_logit    = self.push_logit(h)
        target_logits = self.target_logits(h).view(-1, MAX_FLEETS, MAX_FLEETS)
        return push_logit, target_logits


class NeuralCommander:
    """Drop-in replacement for AICommander with the same public interface."""

    DECISION_INTERVAL = AICommander.DECISION_INTERVAL
    OPENING_TIMEOUT    = AICommander.OPENING_TIMEOUT
    AGGRO_FRACTION     = AICommander.AGGRO_FRACTION

    _shared_policy = None   # lazily-loaded inference-time singleton

    def __init__(self, team: int, enemy_team: int,
                 own_spawn: tuple[float, float], enemy_spawn: tuple[float, float],
                 world_w: float, world_h: float,
                 policy: CommanderPolicy | None = None,
                 team_materials: dict | None = None,
                 miners_ref: list | None = None):
        self.team        = team
        self.enemy_team   = enemy_team
        self.own_spawn    = own_spawn
        self.enemy_spawn  = enemy_spawn
        self.world_w      = world_w
        self.world_h      = world_h

        self.deployed          = False
        self._elapsed          = 0.0
        self._decision_t       = 0.0
        self._rally: dict      = {}   # id(fleet leader) -> (x, y)
        self._team_materials   = team_materials   # shared ref: {team: {mat: float}}
        self._miners_ref       = miners_ref or [] # shared ref: list of MinerShip

        # No usable trained weights (fresh checkout, model deleted, file
        # mid-write from a concurrent training run, architecture mismatch,
        # etc.) — fall back to the rule-based commander entirely rather than
        # acting on a randomly-initialised network, so the game is never
        # worse than before and never crashes on a bad checkpoint file.
        self._fallback = None
        if policy is not None:
            self.policy = policy
            return
        try:
            self.policy = self._load_shared_policy()
        except Exception as exc:
            print(f"[NeuralCommander] couldn't load weights from {MODEL_PATH} "
                  f"({exc!r}) — falling back to AICommander.")
            self._fallback = AICommander(team, enemy_team, own_spawn, enemy_spawn, world_w, world_h)

    # ── Loading ──────────────────────────────────────────────────────────────
    @classmethod
    def _load_shared_policy(cls) -> CommanderPolicy:
        if cls._shared_policy is None:
            net = CommanderPolicy()
            net.load_state_dict(torch.load(MODEL_PATH, map_location='cpu'))
            net.eval()
            cls._shared_policy = net
        return cls._shared_policy

    # ── Main loop hook ───────────────────────────────────────────────────────
    def update(self, dt: float, ai_characters: list) -> None:
        if self._fallback is not None:
            self._fallback.update(dt, ai_characters)
            self.deployed = self._fallback.deployed
            return

        self._elapsed    += dt
        self._decision_t -= dt
        if not self.deployed:
            self._check_deploy(ai_characters)
        if self.deployed and self._decision_t <= 0.0:
            self._decision_t = self.DECISION_INTERVAL
            self._decide(ai_characters)
        self._apply(ai_characters)

    # ── Deploy trigger — identical heuristic to AICommander, intentionally
    #    not learned (cheap and not worth spending training budget on) ────────
    def _check_deploy(self, ai_characters: list) -> None:
        own = [s for s in ai_characters if s.alive and s.team == self.team]
        if not own:
            return
        enemy = [s for s in ai_characters if s.alive and s.team == self.enemy_team]
        triggered = self._elapsed > self.OPENING_TIMEOUT
        if not triggered and enemy:
            ecx, ecy = self._centroid(enemy)
            d = math.hypot(ecx - self.own_spawn[0], ecy - self.own_spawn[1])
            triggered = d < self.AGGRO_FRACTION * self.world_w
        if triggered:
            self.deployed = True
            for s in own:
                s.deployed = True

    # ── Strategy ─────────────────────────────────────────────────────────────
    def _decide(self, ai_characters: list) -> None:
        own_fleets   = self._collect_fleets(ai_characters, self.team)
        enemy_fleets = self._collect_fleets(ai_characters, self.enemy_team)
        if not own_fleets:
            return

        obs = self._build_obs(ai_characters, own_fleets, enemy_fleets)
        push_frac_list, target_idx_list = self.infer(obs, len(own_fleets), len(enemy_fleets))

        for i, (leader, members) in enumerate(own_fleets):
            tgt_idx = target_idx_list[i]
            target_centroid = (self._fleet_centroid(enemy_fleets[tgt_idx][1])
                                if tgt_idx is not None else self.enemy_spawn)

            own_centroid = self._fleet_centroid(members)
            pf = push_frac_list[i]
            rx = own_centroid[0] + (target_centroid[0] - own_centroid[0]) * pf
            ry = own_centroid[1] + (target_centroid[1] - own_centroid[1]) * pf
            self._rally[id(leader)] = (rx, ry)

    def infer(self, obs: list, n_own: int, n_enemy: int):
        """Deterministic forward pass -> (push_frac per fleet, target enemy idx per fleet)."""
        obs_t = torch.tensor(obs, dtype=torch.float32).unsqueeze(0)
        with torch.no_grad():
            push_logit, target_logits = self.policy(obs_t)
        push_frac = torch.sigmoid(push_logit[0]).tolist()

        target_idx = []
        for i in range(n_own):
            if n_enemy > 0:
                target_idx.append(int(torch.argmax(target_logits[0, i, :n_enemy]).item()))
            else:
                target_idx.append(None)
        return push_frac, target_idx

    # ── Execution — identical pattern to AICommander._apply, just per-fleet ──
    def _apply(self, ai_characters: list) -> None:
        if not self.deployed:
            return
        for s in ai_characters:
            if not s.alive or s.team != self.team:
                continue
            is_fleet_leader = s.fleet_leader is None or s.fleet_leader is s
            if is_fleet_leader and s.combat_state == 'patrol':
                rally = self._rally.get(id(s))
                if rally is not None:
                    s._movement_override = rally

    # ── Observation construction ────────────────────────────────────────────
    def _mirror_x(self, x: float) -> float:
        return x if self.team == 0 else (self.world_w - x)

    def _collect_fleets(self, ai_characters: list, team: int):
        """Return [(leader, member_ships)] for `team`, strongest (by total HP) first."""
        carriers = [s for s in ai_characters if s.alive and s.team == team and isinstance(s, Carrier)]
        fleets = []
        for c in carriers:
            members = [s for s in ai_characters if s.alive and s.fleet_leader is c]
            if c not in members:
                members.append(c)
            fleets.append((c, members))
        fleets.sort(key=lambda f: sum(s.hp for s in f[1]), reverse=True)
        return fleets[:MAX_FLEETS]

    @staticmethod
    def _fleet_centroid(ships: list) -> tuple[float, float]:
        sx = sum(s.wx + s.width / 2 for s in ships)
        sy = sum(s.wy + s.height / 2 for s in ships)
        n  = len(ships)
        return (sx / n, sy / n)

    @staticmethod
    def _centroid(ships: list):
        if not ships:
            return None
        sx = sum(s.wx + s.width / 2 for s in ships)
        sy = sum(s.wy + s.height / 2 for s in ships)
        return (sx / len(ships), sy / len(ships))

    def _build_obs(self, ai_characters: list, own_fleets: list, enemy_fleets: list) -> list:
        own_all   = [s for s in ai_characters if s.alive and s.team == self.team]
        enemy_all = [s for s in ai_characters if s.alive and s.team == self.enemy_team]

        own_hp      = sum(s.hp for s in own_all)
        enemy_hp    = sum(s.hp for s in enemy_all)
        own_max_hp  = sum(s.max_hp for s in own_all) or 1.0
        enemy_max_hp = sum(s.max_hp for s in enemy_all) or 1.0
        own_carriers   = sum(1 for s in own_all if isinstance(s, Carrier))
        enemy_carriers = sum(1 for s in enemy_all if isinstance(s, Carrier))
        total_carriers_guess = max(1, MAX_FLEETS)

        ratio = own_hp / max(1.0, enemy_hp)

        feats = [
            own_hp / own_max_hp,
            enemy_hp / enemy_max_hp,
            min(3.0, ratio) / 3.0,
            min(1.0, len(own_all) / 100.0),
            min(1.0, len(enemy_all) / 100.0),
            own_carriers / total_carriers_guess,
            enemy_carriers / total_carriers_guess,
            min(1.0, self._elapsed / 180.0),
        ]

        enemy_centroids = [self._fleet_centroid(m) for _, m in enemy_fleets]

        for i in range(MAX_FLEETS):
            if i < len(own_fleets):
                leader, members = own_fleets[i]
                cx, cy = self._fleet_centroid(members)
                hp_frac = sum(s.hp for s in members) / max(1.0, sum(s.max_hp for s in members))
                nearest_d = min((math.hypot(cx - ex, cy - ey) for ex, ey in enemy_centroids), default=self.world_w)
                feats.extend([
                    hp_frac,
                    min(1.0, len(members) / 30.0),
                    (self._mirror_x(cx) - self._mirror_x(self.own_spawn[0])) / self.world_w,
                    (cy - self.world_h / 2) / self.world_h,
                    min(1.0, nearest_d / self.world_w),
                    1.0,
                ])
            else:
                feats.extend([0.0, 0.0, 0.0, 0.0, 1.0, 0.0])

        for i in range(MAX_FLEETS):
            if i < len(enemy_fleets):
                leader, members = enemy_fleets[i]
                cx, cy = self._fleet_centroid(members)
                hp_frac = sum(s.hp for s in members) / max(1.0, sum(s.max_hp for s in members))
                feats.extend([
                    hp_frac,
                    min(1.0, len(members) / 30.0),
                    (self._mirror_x(cx) - self._mirror_x(self.own_spawn[0])) / self.world_w,
                    (cy - self.world_h / 2) / self.world_h,
                    1.0,
                ])
            else:
                feats.extend([0.0, 0.0, 0.0, 0.0, 0.0])

        # Economy features (6) — own team only; enemy economy is unobservable
        if self._team_materials is not None:
            mat        = self._team_materials.get(self.team, {})
            own_miners = sum(1 for m in self._miners_ref
                             if m.team == self.team and getattr(m, 'alive', True))
            feats.extend([
                min(1.0, mat.get('iron',     0) / 200.0),
                min(1.0, mat.get('copper',   0) / 100.0),
                min(1.0, mat.get('titanium', 0) / 100.0),
                min(1.0, mat.get('crystal',  0) /  80.0),
                min(1.0, mat.get('fuel',     0) / 100.0),
                min(1.0, own_miners            /   5.0),
            ])
        else:
            feats.extend([0.0] * CommanderPolicy.ECONOMY_FEATS)

        return feats
