"""
neural_commander.py — Neural-network fleet commander.

Same role as AICommander (commander.py): decide when the fleet commits to a
push and where each fleet should rally. Where AICommander uses a fixed
push-fraction lookup table keyed on team_strength_ratio, NeuralCommander
asks a small trained policy network for a *per-fleet* push fraction and
target choice every decision tick, learned via self-play (see
train_commander.py).

The observation is egocentric: features are always framed as "own" vs
"enemy", with world-x mirrored for team 1, so the same network weights
produce sensible behaviour for either team and are trainable via symmetric
self-play. Fleets are identified by rank (strongest-HP-first), not by
identity, so the network doesn't need to track which specific carrier is
"fleet 0" across ticks.
"""
import os
import math

import torch
import torch.nn as nn
from torch.distributions import Normal, Categorical

from entities import Carrier
from commander import AICommander

MAX_FLEETS = 4   # matches NUM_CARRIERS_PER_TEAM with the game's default NUM_AI=100

MODEL_PATH = os.path.join(os.path.dirname(__file__), 'models', 'commander_policy.pt')


class CommanderPolicy(nn.Module):
    """Small actor-critic MLP. See module docstring for the observation layout."""

    GLOBAL_FEATS      = 8
    OWN_FLEET_FEATS   = 6
    ENEMY_FLEET_FEATS = 5
    IN_DIM = GLOBAL_FEATS + MAX_FLEETS * OWN_FLEET_FEATS + MAX_FLEETS * ENEMY_FLEET_FEATS  # 52

    def __init__(self, hidden: int = 64):
        super().__init__()
        self.backbone = nn.Sequential(
            nn.Linear(self.IN_DIM, hidden), nn.Tanh(),
            nn.Linear(hidden, hidden),      nn.Tanh(),
        )
        self.push_mean     = nn.Linear(hidden, MAX_FLEETS)
        self.push_logstd   = nn.Parameter(torch.full((MAX_FLEETS,), -0.5))
        self.target_logits = nn.Linear(hidden, MAX_FLEETS * MAX_FLEETS)
        self.value         = nn.Linear(hidden, 1)

    def forward(self, obs: torch.Tensor):
        """obs: (batch, IN_DIM) -> push_mean, push_logstd, target_logits (batch,F,F), value (batch,)"""
        h = self.backbone(obs)
        push_mean     = self.push_mean(h)
        push_logstd   = self.push_logstd.expand_as(push_mean)
        target_logits = self.target_logits(h).view(-1, MAX_FLEETS, MAX_FLEETS)
        value         = self.value(h).squeeze(-1)
        return push_mean, push_logstd, target_logits, value


class NeuralCommander:
    """Drop-in replacement for AICommander with the same public interface."""

    DECISION_INTERVAL = AICommander.DECISION_INTERVAL
    OPENING_TIMEOUT    = AICommander.OPENING_TIMEOUT
    AGGRO_FRACTION     = AICommander.AGGRO_FRACTION

    _shared_policy = None   # lazily-loaded inference-time singleton

    def __init__(self, team: int, enemy_team: int,
                 own_spawn: tuple[float, float], enemy_spawn: tuple[float, float],
                 world_w: float, world_h: float,
                 policy: CommanderPolicy | None = None, stochastic: bool = False):
        self.team        = team
        self.enemy_team   = enemy_team
        self.own_spawn    = own_spawn
        self.enemy_spawn  = enemy_spawn
        self.world_w      = world_w
        self.world_h      = world_h

        self.deployed     = False
        self._elapsed     = 0.0
        self._decision_t  = 0.0
        self._rally: dict = {}   # id(fleet leader) -> (x, y)

        self.stochastic = stochastic     # True during training (sample); False at inference (use mean/argmax)
        self.trajectory: list = []       # filled only when stochastic=True — consumed by the trainer

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
    #    not learned (see plan: cheap and not worth spending training budget on) ──
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
    # Runs gradient-free (the forward pass only needs to produce numbers to
    # act on). Training recomputes log-probs/entropy/value in one batched,
    # grad-enabled pass over the recorded (obs, action) pairs afterwards —
    # see `recompute_batch` below — which is what makes rollout collection
    # safe to run in parallel worker processes that hold no live autograd
    # graph at all.
    def _decide(self, ai_characters: list) -> None:
        own_fleets   = self._collect_fleets(ai_characters, self.team)
        enemy_fleets = self._collect_fleets(ai_characters, self.enemy_team)
        if not own_fleets:
            return

        obs = self._build_obs(ai_characters, own_fleets, enemy_fleets)
        obs_t = torch.tensor(obs, dtype=torch.float32).unsqueeze(0)

        with torch.no_grad():
            push_mean, push_logstd, target_logits, value = self.policy(obs_t)
        push_mean, push_logstd = push_mean[0], push_logstd[0]
        target_logits, value   = target_logits[0], value[0]

        n_enemy = len(enemy_fleets)
        fleet_actions = []   # (z: float, tgt_idx: int|None) per own fleet, in order

        for i, (leader, members) in enumerate(own_fleets):
            std  = torch.exp(push_logstd[i])
            dist = Normal(push_mean[i], std)
            z = dist.sample() if self.stochastic else push_mean[i]
            push_frac = torch.sigmoid(z)

            target_centroid = None
            tgt_idx = None
            if n_enemy > 0:
                logits = target_logits[i, :n_enemy]
                if self.stochastic:
                    tgt_idx = int(Categorical(logits=logits).sample().item())
                else:
                    tgt_idx = int(torch.argmax(logits).item())
                target_centroid = self._fleet_centroid(enemy_fleets[tgt_idx][1])

            fleet_actions.append((float(z.item()), tgt_idx))

            if target_centroid is None:
                target_centroid = self.enemy_spawn

            own_centroid = self._fleet_centroid(members)
            pf = float(push_frac.item())
            rx = own_centroid[0] + (target_centroid[0] - own_centroid[0]) * pf
            ry = own_centroid[1] + (target_centroid[1] - own_centroid[1]) * pf
            self._rally[id(leader)] = (rx, ry)

        if self.stochastic:
            self.trajectory.append({'obs': obs, 'fleets': fleet_actions, 'n_enemy': n_enemy})

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

        return feats


def recompute_batch(policy: CommanderPolicy, ticks: list[dict]):
    """Re-run `policy` (grad-enabled) over a batch of recorded decision ticks
    (the raw dicts NeuralCommander.trajectory accumulates) and return
    (log_probs, entropies, values) each shaped (len(ticks),).

    Used by the trainer to turn gradient-free rollout data — possibly
    collected in a separate worker process — into a loss against the
    *current* policy weights in one batched forward pass.
    """
    eps = 1e-6
    obs_t = torch.tensor([t['obs'] for t in ticks], dtype=torch.float32)
    push_mean, push_logstd, target_logits, values = policy(obs_t)

    log_probs, entropies = [], []
    for row, t in enumerate(ticks):
        std_row = torch.exp(push_logstd[row])
        lp_terms, ent_terms = [], []
        for i, (z, tgt_idx) in enumerate(t['fleets']):
            dist = Normal(push_mean[row, i], std_row[i])
            z_t  = torch.as_tensor(z, dtype=torch.float32)
            push_frac = torch.sigmoid(z_t)
            lp = dist.log_prob(z_t) - torch.log(push_frac * (1 - push_frac) + eps)
            ent = dist.entropy()
            if tgt_idx is not None:
                logits = target_logits[row, i, :t['n_enemy']]
                cat = Categorical(logits=logits)
                lp  = lp + cat.log_prob(torch.as_tensor(tgt_idx))
                ent = ent + cat.entropy()
            lp_terms.append(lp)
            ent_terms.append(ent)
        log_probs.append(torch.stack(lp_terms).sum())
        entropies.append(torch.stack(ent_terms).sum())

    return torch.stack(log_probs), torch.stack(entropies), values
