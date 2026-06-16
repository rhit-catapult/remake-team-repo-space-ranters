"""
train_commander.py — Fast imitation-learning trainer for NeuralCommander.

Generates realistic game states from fast rule-based-vs-rule-based matches
(no neural-net overhead during data generation), labels each fleet's ideal
(push fraction, target fleet) with a richer per-fleet generalisation of
AICommander's own strength-ratio heuristic, then fits CommanderPolicy to
reproduce those labels via ordinary supervised learning — minutes, not the
hours self-play reinforcement learning needed for the same per-fleet
behaviour.
"""
import random
import time
import argparse
import multiprocessing as mp

import torch
import torch.nn.functional as F

from neural_commander import CommanderPolicy, NeuralCommander, MAX_FLEETS, MODEL_PATH
from commander import AICommander
from main import WORLD_W, WORLD_H, _team_spawn_center
import headless_sim


def _push_frac_for_ratio(ratio: float) -> float:
    # Mirrors AICommander._decide's own thresholds — just applied per-fleet
    # against that fleet's nearest enemy instead of one team-wide ratio.
    if ratio > 1.15:
        return 0.95
    if ratio < 0.45:
        return 0.10
    if ratio < 0.75:
        return 0.35
    return 0.60


def _teacher_labels(own_fleets, enemy_fleets):
    """Each fleet reacts to its own local matchup (nearest enemy fleet)
    instead of one shared team-wide ratio — the per-fleet richness the
    network is being taught to reproduce. Returns [(push_frac, target_idx)]
    in the same order as own_fleets; target_idx is None when there's no
    enemy fleet left to rally toward."""
    enemy_info = []
    for _, members in enemy_fleets:
        cx = sum(s.wx + s.width / 2 for s in members) / len(members)
        cy = sum(s.wy + s.height / 2 for s in members) / len(members)
        enemy_info.append((cx, cy, sum(s.hp for s in members)))

    labels = []
    for _, members in own_fleets:
        cx = sum(s.wx + s.width / 2 for s in members) / len(members)
        cy = sum(s.wy + s.height / 2 for s in members) / len(members)
        own_hp = sum(s.hp for s in members)
        if enemy_info:
            nearest_idx = min(range(len(enemy_info)),
                               key=lambda i: (enemy_info[i][0] - cx) ** 2 + (enemy_info[i][1] - cy) ** 2)
            ratio = own_hp / max(1.0, enemy_info[nearest_idx][2])
            labels.append((_push_frac_for_ratio(ratio), nearest_idx))
        else:
            labels.append((0.6, None))
    return labels


def _collect_samples(seed: int, max_seconds: float, dt: float):
    """Play one rule-based-vs-rule-based match, recording (obs, labels) at
    the same 1Hz decision cadence the real commanders use. Runs gradient-free
    and NN-free — pure simulation + arithmetic — so this is fast and safe to
    run in parallel worker processes."""
    random.seed(seed)

    dummy_policy = CommanderPolicy()
    spawn0, spawn1 = _team_spawn_center(0), _team_spawn_center(1)
    helper0 = NeuralCommander(team=0, enemy_team=1, own_spawn=spawn0, enemy_spawn=spawn1,
                               world_w=WORLD_W, world_h=WORLD_H, policy=dummy_policy)
    helper1 = NeuralCommander(team=1, enemy_team=0, own_spawn=spawn1, enemy_spawn=spawn0,
                               world_w=WORLD_W, world_h=WORLD_H, policy=dummy_policy)

    samples = []
    tick_t = [0.0]

    def on_tick(ai_characters, c0, c1):
        tick_t[0] += dt
        if tick_t[0] < 1.0:
            return
        tick_t[0] = 0.0
        for commander, helper in ((c0, helper0), (c1, helper1)):
            if not commander.deployed:
                continue
            helper._elapsed = commander._elapsed
            own_fleets   = helper._collect_fleets(ai_characters, helper.team)
            enemy_fleets = helper._collect_fleets(ai_characters, helper.enemy_team)
            if not own_fleets:
                continue
            obs    = helper._build_obs(ai_characters, own_fleets, enemy_fleets)
            labels = _teacher_labels(own_fleets, enemy_fleets)
            samples.append({'obs': obs, 'labels': labels, 'n_enemy': len(enemy_fleets)})

    def factory(team, enemy_team, own_spawn, enemy_spawn, world_w, world_h):
        return AICommander(team, enemy_team, own_spawn, enemy_spawn, world_w, world_h)

    headless_sim.run_match(factory, factory, max_seconds=max_seconds, dt=dt, on_tick=on_tick)
    return samples


def generate_dataset(num_matches: int, workers: int, max_seconds: float, dt: float) -> list:
    seeds = [random.randint(0, 2**31 - 1) for _ in range(num_matches)]
    jobs  = [(s, max_seconds, dt) for s in seeds]
    ctx = mp.get_context('spawn')
    with ctx.Pool(processes=workers) as pool:
        results = pool.starmap(_collect_samples, jobs)
    samples = [s for r in results for s in r]
    return samples


def train(samples: list, epochs: int, lr: float) -> CommanderPolicy:
    n = len(samples)
    obs_t = torch.tensor([s['obs'] for s in samples], dtype=torch.float32)

    push_label   = torch.zeros(n, MAX_FLEETS)
    own_mask     = torch.zeros(n, MAX_FLEETS)
    target_label = torch.zeros(n, MAX_FLEETS, dtype=torch.long)
    target_mask  = torch.zeros(n, MAX_FLEETS)
    enemy_valid  = torch.zeros(n, MAX_FLEETS)

    for row, s in enumerate(samples):
        enemy_valid[row, :s['n_enemy']] = 1.0
        for i, (pf, tgt) in enumerate(s['labels']):
            own_mask[row, i]   = 1.0
            push_label[row, i] = pf
            if tgt is not None:
                target_label[row, i] = tgt
                target_mask[row, i]  = 1.0

    policy    = CommanderPolicy()
    optimizer = torch.optim.Adam(policy.parameters(), lr=lr)
    neg_inf   = -1e9

    for epoch in range(epochs):
        push_logit, target_logits = policy(obs_t)
        push_pred  = torch.sigmoid(push_logit)
        push_loss  = (((push_pred - push_label) ** 2) * own_mask).sum() / own_mask.sum().clamp(min=1)

        masked_logits = target_logits.masked_fill(enemy_valid.unsqueeze(1) == 0, neg_inf)
        logp     = F.log_softmax(masked_logits, dim=-1)
        gathered = logp.gather(-1, target_label.unsqueeze(-1)).squeeze(-1)
        target_loss = -(gathered * target_mask).sum() / target_mask.sum().clamp(min=1)

        loss = push_loss + target_loss
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()

        if epoch % 20 == 0 or epoch == epochs - 1:
            print(f"[train] epoch {epoch:4d} | push_loss {push_loss.item():.4f} | "
                  f"target_loss {target_loss.item():.4f}", flush=True)

    return policy


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--matches',     type=int,   default=24)
    ap.add_argument('--workers',     type=int,   default=12)
    ap.add_argument('--max-seconds', type=float, default=150.0)
    ap.add_argument('--dt',          type=float, default=0.05)
    ap.add_argument('--epochs',      type=int,   default=400)
    ap.add_argument('--lr',          type=float, default=1e-2)
    args = ap.parse_args()

    t0 = time.time()
    print(f"[train] generating dataset from {args.matches} rule-based-vs-rule-based "
          f"matches across {args.workers} workers...", flush=True)
    samples = generate_dataset(args.matches, args.workers, args.max_seconds, args.dt)
    t1 = time.time()
    print(f"[train] collected {len(samples)} decision samples in {t1 - t0:.1f}s", flush=True)

    if not samples:
        print("[train] no samples collected (matches too short to deploy) — aborting")
        return

    policy = train(samples, args.epochs, args.lr)
    t2 = time.time()
    print(f"[train] trained {args.epochs} epochs in {t2 - t1:.1f}s", flush=True)

    torch.save(policy.state_dict(), MODEL_PATH)
    print(f"[train] saved weights to {MODEL_PATH} (total wall time {t2 - t0:.1f}s)", flush=True)


if __name__ == '__main__':
    main()
