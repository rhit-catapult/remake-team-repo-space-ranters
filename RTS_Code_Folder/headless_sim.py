"""
headless_sim.py — Render-free match simulation for commander training.

Reuses the exact game setup/update logic from main.py (setup_game,
update_team_strategy, fleet assignment, fighter spawning) but skips every
pygame display/font/draw call, so a full match can be simulated far faster
than real time. Both teams are driven by commander-like objects (anything
exposing the same update(dt, ai_characters) interface as AICommander) —
there is no human player in a headless match.
"""
import math
import random

from entities import Carrier, Fighter
from main import setup_game, update_team_strategy, _make_waypoints, _team_spawn_center, WORLD_W, WORLD_H


def run_match(commander0_factory, commander1_factory,
              max_seconds: float = 120.0, dt: float = 0.05, on_tick=None) -> dict:
    """Simulate one match between two commanders, one per team.

    commanderN_factory(team, enemy_team, own_spawn, enemy_spawn, world_w, world_h)
    must return an object with .update(dt, ai_characters).

    on_tick(ai_characters, commander0, commander1), if given, is called once
    per simulated frame — e.g. for a trainer that wants to sample game
    states at its own cadence rather than collecting trajectories off the
    commanders themselves.

    Returns a dict of final stats plus the two commander instances (so a
    trainer can pull per-decision trajectories off them if they recorded any).
    """
    ai_characters = setup_game()
    lasers: list = []

    spawn0 = _team_spawn_center(0)
    spawn1 = _team_spawn_center(1)
    commander0 = commander0_factory(team=0, enemy_team=1, own_spawn=spawn0, enemy_spawn=spawn1,
                                     world_w=WORLD_W, world_h=WORLD_H)
    commander1 = commander1_factory(team=1, enemy_team=0, own_spawn=spawn1, enemy_spawn=spawn0,
                                     world_w=WORLD_W, world_h=WORLD_H)

    initial_max_hp = {
        0: sum(s.max_hp for s in ai_characters if s.team == 0),
        1: sum(s.max_hp for s in ai_characters if s.team == 1),
    }

    elapsed = 0.0
    while elapsed < max_seconds:
        elapsed += dt

        for ship in ai_characters:
            ship.update(dt)
            ship.wx = max(0.0, min(WORLD_W - ship.width,  ship.wx))
            ship.wy = max(0.0, min(WORLD_H - ship.height, ship.wy))

        update_team_strategy(ai_characters)

        for ship in ai_characters:
            ship.update_combat(dt, ai_characters, lasers)
        lasers.clear()   # purely visual — never needed headless

        commander0.update(dt, ai_characters)
        commander1.update(dt, ai_characters)

        if on_tick is not None:
            on_tick(ai_characters, commander0, commander1)

        new_fighters = []
        for ship in ai_characters:
            if isinstance(ship, Carrier) and ship._spawn_queue:
                for fx, fy, fteam in ship._spawn_queue:
                    wp = _make_waypoints()
                    fighter = Fighter(fx, fy, wp, fteam, home_carrier=ship)
                    fighter.fleet_leader = ship
                    fighter.deployed     = True
                    angle = random.uniform(0, math.tau)
                    fighter.fleet_offset = (math.cos(angle) * 200, math.sin(angle) * 200)
                    ship._active_fighters.append(fighter)
                    new_fighters.append(fighter)
                ship._spawn_queue.clear()
        if new_fighters:
            ai_characters.extend(new_fighters)

        alive0 = any(s.alive for s in ai_characters if s.team == 0)
        alive1 = any(s.alive for s in ai_characters if s.team == 1)
        if not alive0 or not alive1:
            break

    hp = {
        0: sum(s.hp for s in ai_characters if s.team == 0 and s.alive),
        1: sum(s.hp for s in ai_characters if s.team == 1 and s.alive),
    }
    count = {
        0: sum(1 for s in ai_characters if s.team == 0 and s.alive),
        1: sum(1 for s in ai_characters if s.team == 1 and s.alive),
    }

    return {
        'elapsed':         elapsed,
        'hp':              hp,
        'initial_max_hp':  initial_max_hp,
        'count':           count,
        'commander0':      commander0,
        'commander1':      commander1,
        'wiped':           (count[0] == 0) or (count[1] == 0),
    }
