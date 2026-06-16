"""
train_commander.py — Self-play trainer for NeuralCommander.

Each round:
  1. Broadcast the current policy weights to a pool of worker processes.
  2. Each worker plays one full self-play match headless (both teams share
     the same weights, gradient-free) and returns the raw decision-tick
     data plus a terminal reward for each team.
  3. The main process re-runs the *current* policy over the whole batch of
     recorded ticks in one shot (recompute_batch) to get gradient-tracked
     log-probs/entropy/value, then does a single REINFORCE-with-baseline
     update (policy loss + value loss − entropy bonus).

Checkpoints to models/commander_policy.pt periodically and resumes from it
automatically, so this is safe to stop (Ctrl+C) and restart at any time.
Every --eval-every rounds it also plays the *deterministic* policy against
the rule-based AICommander baseline — self-play reward alone can drift
without the policy actually getting better, so this is the real progress
signal.
"""
import os
import json
import random
import time
import argparse
import multiprocessing as mp

import torch
import torch.nn.functional as F

from neural_commander import CommanderPolicy, NeuralCommander, recompute_batch, MODEL_PATH
from commander import AICommander
import headless_sim

TRAIN_STATE_PATH = MODEL_PATH + '.train.json'


def _play_match(state_dict, max_seconds, dt, seed):
    random.seed(seed)
    torch.manual_seed(seed)
    policy = CommanderPolicy()
    policy.load_state_dict(state_dict)
    policy.eval()

    def factory(team, enemy_team, own_spawn, enemy_spawn, world_w, world_h):
        return NeuralCommander(team, enemy_team, own_spawn, enemy_spawn, world_w, world_h,
                                policy=policy, stochastic=True)

    result = headless_sim.run_match(factory, factory, max_seconds=max_seconds, dt=dt)
    c0, c1 = result['commander0'], result['commander1']
    count  = result['count']
    hp_frac = {t: result['hp'][t] / max(1.0, result['initial_max_hp'][t]) for t in (0, 1)}

    reward = {}
    for t in (0, 1):
        e = 1 - t
        r = hp_frac[t] - hp_frac[e]
        if count[t] == 0 and count[e] > 0:
            r -= 1.0
        elif count[e] == 0 and count[t] > 0:
            r += 1.0
        reward[t] = r

    win = None
    if count[0] == 0 and count[1] > 0:
        win = 1
    elif count[1] == 0 and count[0] > 0:
        win = 0
    elif hp_frac[0] != hp_frac[1]:
        win = 0 if hp_frac[0] > hp_frac[1] else 1

    return {
        'ticks0': c0.trajectory, 'reward0': reward[0],
        'ticks1': c1.trajectory, 'reward1': reward[1],
        'win': win, 'elapsed': result['elapsed'],
    }


def _eval_match(state_dict, neural_team, max_seconds, dt, seed):
    """Deterministic NeuralCommander (playing `neural_team`) vs rule-based AICommander."""
    random.seed(seed)
    torch.manual_seed(seed)
    policy = CommanderPolicy()
    policy.load_state_dict(state_dict)
    policy.eval()

    def neural_factory(team, enemy_team, own_spawn, enemy_spawn, world_w, world_h):
        return NeuralCommander(team, enemy_team, own_spawn, enemy_spawn, world_w, world_h,
                                policy=policy, stochastic=False)

    def rule_factory(team, enemy_team, own_spawn, enemy_spawn, world_w, world_h):
        return AICommander(team, enemy_team, own_spawn, enemy_spawn, world_w, world_h)

    if neural_team == 0:
        result = headless_sim.run_match(neural_factory, rule_factory, max_seconds=max_seconds, dt=dt)
    else:
        result = headless_sim.run_match(rule_factory, neural_factory, max_seconds=max_seconds, dt=dt)

    enemy_team = 1 - neural_team
    count = result['count']
    hp_frac = {t: result['hp'][t] / max(1.0, result['initial_max_hp'][t]) for t in (0, 1)}

    if count[neural_team] == 0 and count[enemy_team] > 0:
        return False
    if count[enemy_team] == 0 and count[neural_team] > 0:
        return True
    return hp_frac[neural_team] > hp_frac[enemy_team]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--episodes',      type=int,   default=10_000_000)
    ap.add_argument('--workers',       type=int,   default=max(1, (os.cpu_count() or 4) - 2))
    ap.add_argument('--batch-episodes', type=int,  default=None)
    ap.add_argument('--max-seconds',   type=float, default=150.0)
    ap.add_argument('--dt',            type=float, default=0.05)
    ap.add_argument('--lr',            type=float, default=3e-4)
    ap.add_argument('--value-coef',    type=float, default=0.5)
    ap.add_argument('--entropy-coef',  type=float, default=0.002)
    ap.add_argument('--eval-every',    type=int,   default=10)
    ap.add_argument('--eval-matches',  type=int,   default=6)
    ap.add_argument('--save-every',    type=int,   default=2)
    ap.add_argument('--no-resume',     action='store_true')
    args = ap.parse_args()

    batch_episodes = args.batch_episodes or args.workers

    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    policy = CommanderPolicy()

    round_idx, episodes_done = 0, 0
    if not args.no_resume and os.path.exists(MODEL_PATH):
        policy.load_state_dict(torch.load(MODEL_PATH, map_location='cpu'))
        print(f"[train] resumed weights from {MODEL_PATH}")
        if os.path.exists(TRAIN_STATE_PATH):
            with open(TRAIN_STATE_PATH) as f:
                state = json.load(f)
            round_idx     = state.get('round', 0)
            episodes_done = state.get('episodes_done', 0)
            print(f"[train] resumed training state: round {round_idx}, {episodes_done} episodes")

    optimizer = torch.optim.Adam(policy.parameters(), lr=args.lr)

    ctx  = mp.get_context('spawn')
    pool = ctx.Pool(processes=args.workers)
    print(f"[train] {args.workers} worker processes, {batch_episodes} episodes/round, "
          f"max_seconds={args.max_seconds} dt={args.dt}", flush=True)

    t_start = time.time()
    win_history: list = []

    def checkpoint():
        # Atomic write — the live game may load MODEL_PATH from a separate
        # process at any moment; os.replace() never exposes a partial file.
        tmp_path = MODEL_PATH + '.tmp'
        torch.save(policy.state_dict(), tmp_path)
        os.replace(tmp_path, MODEL_PATH)
        with open(TRAIN_STATE_PATH, 'w') as f:
            json.dump({'round': round_idx, 'episodes_done': episodes_done,
                       'win_history': win_history[-500:]}, f)

    try:
        while episodes_done < args.episodes:
            state_dict = {k: v.cpu() for k, v in policy.state_dict().items()}
            seeds = [random.randint(0, 2**31 - 1) for _ in range(batch_episodes)]
            jobs  = [(state_dict, args.max_seconds, args.dt, s) for s in seeds]
            results = pool.starmap(_play_match, jobs)

            all_ticks, all_returns = [], []
            for r in results:
                if r['ticks0']:
                    all_ticks.extend(r['ticks0']); all_returns.extend([r['reward0']] * len(r['ticks0']))
                if r['ticks1']:
                    all_ticks.extend(r['ticks1']); all_returns.extend([r['reward1']] * len(r['ticks1']))
                if r['win'] is not None:
                    win_history.append(r['win'])

            episodes_done += len(results)
            round_idx += 1

            if not all_ticks:
                print(f"[train] round {round_idx}: no decision ticks recorded this round "
                      f"(matches ended before any deploy) — skipping update", flush=True)
                continue

            log_probs, entropies, values = recompute_batch(policy, all_ticks)
            returns_t   = torch.tensor(all_returns, dtype=torch.float32)
            advantage   = returns_t - values.detach()
            policy_loss = -(log_probs * advantage).mean()
            value_loss  = F.mse_loss(values, returns_t)
            entropy_avg = entropies.mean()
            loss = policy_loss + args.value_coef * value_loss - args.entropy_coef * entropy_avg

            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(policy.parameters(), 1.0)
            optimizer.step()

            mean_return = sum(all_returns) / len(all_returns)
            recent_wr   = (sum(win_history[-50:]) / len(win_history[-50:])) if win_history else float('nan')
            wall_min    = (time.time() - t_start) / 60.0
            print(f"[train] round {round_idx:5d} | episodes {episodes_done:6d} | "
                  f"loss {loss.item():+.4f} (pi {policy_loss.item():+.4f} v {value_loss.item():.4f} "
                  f"ent {entropy_avg.item():.3f}) | mean_return {mean_return:+.3f} | "
                  f"team0_winrate(last50) {recent_wr:.2f} | wall {wall_min:.1f}m", flush=True)

            if round_idx % args.save_every == 0:
                checkpoint()
                print(f"[train] checkpoint saved (round {round_idx})", flush=True)

            if round_idx % args.eval_every == 0:
                eval_state = {k: v.cpu() for k, v in policy.state_dict().items()}
                eval_jobs = [
                    (eval_state, i % 2, args.max_seconds, args.dt, random.randint(0, 2**31 - 1))
                    for i in range(args.eval_matches)
                ]
                eval_results = pool.starmap(_eval_match, eval_jobs)
                win_rate = sum(1 for w in eval_results if w) / len(eval_results)
                print(f"[train] === eval vs rule-based AICommander: "
                      f"{win_rate * 100:.0f}% win rate over {len(eval_results)} matches ===", flush=True)

    except KeyboardInterrupt:
        print("[train] interrupted — saving checkpoint and exiting", flush=True)
    finally:
        checkpoint()
        print(f"[train] final checkpoint: round {round_idx}, {episodes_done} episodes", flush=True)
        pool.close()
        pool.join()


if __name__ == '__main__':
    main()
