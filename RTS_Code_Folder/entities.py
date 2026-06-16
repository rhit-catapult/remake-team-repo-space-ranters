"""
entity.py — Game objects that exist in world space.
All positions are world coordinates; the camera handles rendering.
"""
import math
import random
import pygame


class Entity:
    """Base class. Lives in world space; knows nothing about the screen."""

    def __init__(self, wx: float, wy: float, width: int, height: int, color):
        self.wx = wx
        self.wy = wy
        self.width = width
        self.height = height
        self.color = color

    @property
    def world_rect(self) -> pygame.Rect:
        return pygame.Rect(int(self.wx), int(self.wy), self.width, self.height)

    def update(self, dt: float):
        pass

    def draw(self, surface: pygame.Surface, camera):
        if camera.is_visible(self.world_rect):
            screen_rect = camera.world_rect_to_screen(self.world_rect)
            pygame.draw.rect(surface, self.color, screen_rect)


class Player(Entity):
    """Player-controlled entity."""

    SPEED = 200

    def __init__(self, wx: float, wy: float):
        super().__init__(wx, wy, 8, 8, (80, 180, 255))

    def update(self, dt: float):
        keys = pygame.key.get_pressed()
        dx = (keys[pygame.K_d] or keys[pygame.K_RIGHT]) - (keys[pygame.K_a] or keys[pygame.K_LEFT])
        dy = (keys[pygame.K_s] or keys[pygame.K_DOWN]) - (keys[pygame.K_w] or keys[pygame.K_UP])
        if dx and dy:
            dx *= 0.7071
            dy *= 0.7071
        self.wx += dx * self.SPEED * dt
        self.wy += dy * self.SPEED * dt

    def draw(self, surface, camera):
        super().draw(surface, camera)
        if camera.is_visible(self.world_rect):
            cx, cy = camera.world_to_screen(self.wx + self.width / 2, self.wy + self.height / 2)
            pygame.draw.circle(surface, (255, 255, 255), (cx, cy), 2)


# Team colour palettes: index 0 = team 0 (blue), index 1 = team 1 (red)
_TEAM_COLORS = [
    [(60, 140, 255), (80, 180, 255), (40, 100, 220)],   # Team 0 — blues
    [(255, 60,  60), (255, 100, 80), (200, 40,  40)],   # Team 1 — reds
]

# ── Combat tuning ─────────────────────────────────────────────────────────────
ATTACK_RANGE     = 600.0   # world units — laser engagement range
FIRE_RATE        = 2.0     # seconds between shots (lower = faster firing)
TURRET_TURN_RATE = 3.5     # radians / second — how fast the turret rotates
FLANK_OFFSET     = 320.0   # perpendicular distance flankers aim for beside an enemy
RETREAT_HP_RATIO = 0.28    # fraction of max HP at which a ship breaks off and flees
SEPARATION_DIST  = 160.0   # allied ships push apart when closer than this
SEPARATION_FORCE = 50.0    # acceleration magnitude for the separation push
AA_RANGE         = 350.0   # carrier anti-aircraft turret range (shorter than ATTACK_RANGE)
FIXED_GUN_ARC    = 0.22    # radians — half firing arc for fixed forward guns (~12.6°)
FLEET_STRAY_DIST = 900.0   # world units — max distance from fleet slot before returning


class Laser:
    """Instant-hit beam weapon — purely a visual effect; damage is applied at fire time."""

    DURATION = 0.10   # seconds the beam remains visible

    _OUTER = [(40, 100, 255),  (255, 50,  40) ]   # outer glow colour per team
    _INNER = [(180, 220, 255), (255, 200, 180)]   # bright core colour per team

    def __init__(self, x1: float, y1: float, x2: float, y2: float, team: int):
        self.x1, self.y1 = x1, y1   # gun world position
        self.x2, self.y2 = x2, y2   # target world position
        self.team     = team
        self.lifetime = self.DURATION
        self.alive    = True

    def update(self, dt: float) -> None:
        self.lifetime -= dt
        if self.lifetime <= 0:
            self.alive = False

    def draw(self, surface: pygame.Surface, camera) -> None:
        if not self.alive:
            return
        sx1, sy1 = camera.world_to_screen(self.x1, self.y1)
        sx2, sy2 = camera.world_to_screen(self.x2, self.y2)
        t       = self.lifetime / self.DURATION   # 1 = fresh, 0 = dying
        outer   = self._OUTER[self.team]
        inner   = self._INNER[self.team]
        w_outer = max(2, int(4 * t))
        pygame.draw.line(surface, outer, (int(sx1), int(sy1)), (int(sx2), int(sy2)), w_outer)
        pygame.draw.line(surface, inner, (int(sx1), int(sy1)), (int(sx2), int(sy2)), 1)


class DestroyerBeam(Laser):
    """Massive energy beam fired by the Destroyer's main cannon."""

    DURATION = 0.45   # lingers longer than a regular laser

    _BEAM_OUTER = [(20, 130, 255), (255, 75,  20)]   # wide glow per team
    _BEAM_INNER = [(160, 220, 255), (255, 195, 130)]  # bright core per team

    def draw(self, surface: pygame.Surface, camera) -> None:
        if not self.alive:
            return
        sx1, sy1 = camera.world_to_screen(self.x1, self.y1)
        sx2, sy2 = camera.world_to_screen(self.x2, self.y2)
        t       = self.lifetime / self.DURATION
        w_outer = max(4, int(18 * t))
        w_core  = max(2, int(7  * t))
        outer   = self._BEAM_OUTER[self.team]
        inner   = self._BEAM_INNER[self.team]
        pygame.draw.line(surface, outer,
                         (int(sx1), int(sy1)), (int(sx2), int(sy2)), w_outer)
        pygame.draw.line(surface, inner,
                         (int(sx1), int(sy1)), (int(sx2), int(sy2)), w_core)
        pygame.draw.line(surface, (255, 255, 255),
                         (int(sx1), int(sy1)), (int(sx2), int(sy2)), max(1, w_core // 3))


class Explosion:
    """Particle burst that plays when a ship is destroyed.

    Each particle is stored as a list:
      [wx, wy, vx, vy, lifetime, max_lifetime, base_radius]
    """

    # Fire colour ramp: index 0 = dying (dark), index 4 = fresh (bright)
    _RAMP = [
        ( 80,  10,   0),
        (200,  40,  10),
        (255, 120,  20),
        (255, 200,  50),
        (255, 255, 200),
    ]

    def __init__(self, wx: float, wy: float, ship_w: int, ship_h: int):
        self.alive = True
        size  = math.hypot(ship_w, ship_h)          # diagonal of the dead ship
        count = max(18, int(size * 0.28))
        spread = size * 0.35

        # Central flash particle — large, very short-lived
        self._particles = [[wx, wy, 0.0, 0.0, 0.18, 0.18, size * 0.55]]

        for _ in range(count):
            angle = random.uniform(0, math.tau)
            speed = random.uniform(25, size * 1.4)
            lt    = random.uniform(0.45, 1.7)
            r     = random.uniform(1.5, max(2.5, size * 0.065))
            self._particles.append([
                wx + random.uniform(-spread, spread),
                wy + random.uniform(-spread, spread),
                math.cos(angle) * speed,
                math.sin(angle) * speed,
                lt, lt, r,
            ])

    def update(self, dt: float) -> None:
        drag = 0.55 ** dt       # speed drops to 55% per second
        any_alive = False
        for p in self._particles:
            if p[4] <= 0:
                continue
            p[0] += p[2] * dt
            p[1] += p[3] * dt
            p[2] *= drag
            p[3] *= drag
            p[4] -= dt
            any_alive = True
        self.alive = any_alive

    @staticmethod
    def _color(t: float) -> tuple[int, int, int]:
        """Map t ∈ [0,1] (0=dying, 1=fresh) to a fire colour."""
        ramp = Explosion._RAMP
        t  = max(0.0, min(1.0, t))
        s  = t * (len(ramp) - 1)
        i  = min(int(s), len(ramp) - 2)
        f  = s - i
        c0, c1 = ramp[i], ramp[i + 1]
        return (int(c0[0] + (c1[0] - c0[0]) * f),
                int(c0[1] + (c1[1] - c0[1]) * f),
                int(c0[2] + (c1[2] - c0[2]) * f))

    def draw(self, surface: pygame.Surface, camera) -> None:
        sw = camera.screen_width
        sh = camera.screen_height
        for p in self._particles:
            if p[4] <= 0:
                continue
            sx, sy = camera.world_to_screen(p[0], p[1])
            if sx < -30 or sx > sw + 30 or sy < -30 or sy > sh + 30:
                continue
            t = p[4] / p[5]                            # fraction of lifetime remaining
            r = max(1, int(p[6] * camera.zoom * (0.25 + 0.75 * t)))
            pygame.draw.circle(surface, self._color(t), (int(sx), int(sy)), r)


class AICharacter(Entity):
    """
    Spaceship AI with team tactics: roles, state machine, target spreading,
    aim leading, flanking, intercept chasing, retreat, and allied separation.

    Roles (assigned at spawn):
      attacker — charges enemies head-on, cutting off escape with intercept movement.
      flanker  — circles to a position perpendicular to the enemy's travel direction.

    Combat states:
      patrol  — no enemy detected; flying between waypoints.
      engage  — chasing a target using intercept prediction.
      flank   — moving to a perpendicular attack position beside the target.
      retreat — HP critical; fleeing away from the nearest enemy.

    Movement phases (used in all states):
      Cruise  — turn toward destination, thrust when roughly aligned.
      Braking — face retrograde, thrust to shed speed near the destination.
    """

    # Fixed physics constants — same for all ships
    DRAG        = 0.97   # speed multiplier per second
    DECEL_DIST  = 250.0  # world units — start braking phase
    ARRIVE_DIST =  40.0  # world units — waypoint counted as reached

    # Visual dot color per combat state shown on the ship nose
    _STATE_COLORS = {
        'patrol':  (110, 110, 110),
        'engage':  (255, 160,  30),
        'flank':   ( 50, 220,  70),
        'retreat': (230,  30,  30),
    }

    # Turret local positions as (lx_frac, ly_frac) — fractions of half-width / half-height.
    # Applied after rotating by the ship angle, so turrets move with the hull.
    _TURRET_LAYOUTS = {
        1: [(  0.00,  0.00)],
        2: [(  0.25,  0.00), (-0.30,  0.00)],
        3: [(  0.30,  0.00), (-0.20, -0.45), (-0.20,  0.45)],
    }

    def __init__(self, wx: float, wy: float, waypoints: list[tuple[float, float]],
                 team: int = 0, _w: int = None, _h: int = None):
        if _w is not None:
            w, h = _w, _h
            big  = w >= 88
        else:
            big = random.random() > 0.5
            if big:
                w = random.randint(88, 144)
                h = random.randint(40, 72)
            else:
                w = random.randint(48, 80)
                h = random.randint(24, 40)

        color = random.choice(_TEAM_COLORS[team])
        super().__init__(wx, wy, w, h, color)

        self.team       = team
        self.waypoints  = waypoints
        self.current_wp = 0
        self.vx         = 0.0
        self.vy         = 0.0
        self.angle               = random.uniform(0, math.tau)
        self._thrusting          = False
        self._dampening          = False
        self._thruster_particles = []   # [wx, wy, vx, vy, age, max_age, r0, kind]

        # ── Per-ship stats scaled by size class ───────────────────────────
        if big:
            # Capital ships: slow, tanky, heavy guns, multiple turrets
            self.max_speed     = random.uniform(190, 270)
            self.thrust        = random.uniform(100, 140)
            self.turn_rate     = random.uniform(1.0,  2.0)
            self.fire_rate     = random.uniform(2.5,  4.0)
            self.bullet_damage = random.randint(10,  18)
            self.max_hp        = random.randint(80, 140)
            num_turrets        = random.choice([2, 2, 3])
        else:
            # Frigates: agile, fragile, light guns, forward-facing fixed guns
            self.max_speed     = random.uniform(480, 620)
            self.thrust        = random.uniform(190, 250)
            self.turn_rate     = random.uniform(3.0,  4.5)
            self.fire_rate     = random.uniform(0.9,  1.7)
            self.bullet_damage = random.randint(3,    5)
            self.max_hp        = random.randint(25,  55)

        self.hp    = self.max_hp
        self.alive = True
        self._has_target = False

        # Build weapon system
        # Capital ships: multiple rotating turrets only
        # Frigates:      1 rotating centre turret + 2 fixed forward nose cannons
        if big:
            self.gun_type = 'turret'
            layout = self._TURRET_LAYOUTS[num_turrets]
            self.turrets = [
                {
                    'lx':      lx,
                    'ly':      ly,
                    'angle':   random.uniform(0, math.tau),
                    'cooldown': random.uniform(0, self.fire_rate),
                }
                for lx, ly in layout
            ]
            self.fixed_guns = []
        else:
            self.gun_type = 'both'
            self.turrets = [{
                'lx': 0.0, 'ly': 0.0,
                'angle':    random.uniform(0, math.tau),
                'cooldown': random.uniform(0, self.fire_rate),
            }]
            self.fixed_guns = [
                {'lx': 0.72, 'ly': -0.28, 'cooldown': random.uniform(0, self.fire_rate)},
                {'lx': 0.72, 'ly':  0.28, 'cooldown': random.uniform(0, self.fire_rate)},
            ]

        # Tactics
        self.attack_range       = ATTACK_RANGE   # subclasses may shorten this
        self._detection_range   = ATTACK_RANGE * 1.5  # how far away enemies are noticed
        self.role               = 'flanker' if random.random() < 0.35 else 'attacker'
        self.combat_state       = 'patrol'
        self._current_target    = None
        self._flank_side        = random.choice([-1, 1])
        self._movement_override = None
        self._sep_ax            = 0.0
        self._sep_ay            = 0.0

        # Fleet assignment — set by main.py after all ships are spawned
        self.fleet_leader     = None              # reference to the carrier/lead ship of this fleet
        self.fleet_offset     = (0.0, 0.0)        # formation slot offset from leader centre
        self.fleet_stray_dist = FLEET_STRAY_DIST  # per-ship leash; escorts get a tighter value

    @property
    def target(self) -> tuple[float, float]:
        return self.waypoints[self.current_wp]

    @property
    def world_rect(self) -> pygame.Rect:
        half_diag = math.hypot(self.width, self.height) / 2
        return pygame.Rect(
            int(self.wx + self.width  / 2 - half_diag),
            int(self.wy + self.height / 2 - half_diag),
            int(half_diag * 2),
            int(half_diag * 2),
        )

    # ── Movement ──────────────────────────────────────────────────────────────

    def update(self, dt: float):
        if not self.alive:
            return

        cx = self.wx + self.width  / 2
        cy = self.wy + self.height / 2

        # Combat overrides the waypoint destination when active
        if self._movement_override is not None:
            tx, ty = self._movement_override
        else:
            tx, ty = self.target

        dx   = tx - cx
        dy   = ty - cy
        dist = math.hypot(dx, dy)

        self._thrusting = False
        self._dampening = False

        if self._movement_override is None and dist < self.ARRIVE_DIST:
            self.current_wp = (self.current_wp + 1) % len(self.waypoints)
            desired_vx, desired_vy = 0.0, 0.0
            self._dampening = True
        elif dist > 2.0:
            target_angle = math.atan2(dy, dx)
            self._turn_toward(target_angle, dt)

            decel = self.DECEL_DIST if self._movement_override is None else self.DECEL_DIST * 0.55
            if dist < decel:
                desired_speed = self.max_speed * (dist / decel)
                self._dampening = True
            else:
                desired_speed = self.max_speed
                self._thrusting = True

            desired_vx = math.cos(target_angle) * desired_speed
            desired_vy = math.sin(target_angle) * desired_speed
        else:
            desired_vx, desired_vy = 0.0, 0.0

        # Smoothly steer velocity toward the desired value — prevents jerking
        # when targets change or the ship is mid-turn
        t = min(1.0, 9.0 * dt)
        self.vx += (desired_vx - self.vx) * t
        self.vy += (desired_vy - self.vy) * t

        # Apply separation impulse (brief push; velocity resets next frame)
        self.vx += self._sep_ax * dt
        self.vy += self._sep_ay * dt
        self._sep_ax = 0.0
        self._sep_ay = 0.0

        # Hard cap so separation bursts don't send ships flying
        speed = math.hypot(self.vx, self.vy)
        if speed > self.max_speed * 1.4:
            f = self.max_speed * 1.4 / speed
            self.vx *= f
            self.vy *= f

        self.wx += self.vx * dt
        self.wy += self.vy * dt
        self._emit_particles(dt)

    # ── Combat & tactics ──────────────────────────────────────────────────────

    def update_combat(self, dt: float, all_ships: list, lasers: list) -> None:
        """Update tactics, movement intent, weapon aim, and firing each frame."""
        if not self.alive:
            return

        cx = self.wx + self.width  / 2
        cy = self.wy + self.height / 2

        # ── Separation: push away from nearby allies ──────────────────────
        for ship in all_ships:
            if ship is self or ship.team != self.team or not ship.alive:
                continue
            ox = ship.wx + ship.width  / 2
            oy = ship.wy + ship.height / 2
            d  = math.hypot(ox - cx, oy - cy)
            if 0 < d < SEPARATION_DIST:
                strength = (SEPARATION_DIST - d) / SEPARATION_DIST * SEPARATION_FORCE
                self._sep_ax += (cx - ox) / d * strength
                self._sep_ay += (cy - oy) / d * strength

        # ── Retreat: break off when critically damaged ────────────────────
        if self.hp / self.max_hp < RETREAT_HP_RATIO:
            self.combat_state       = 'retreat'
            self._current_target    = None
            self._movement_override = self._calc_retreat_pos(cx, cy, all_ships)
            self._aim_and_fire(dt, cx, cy, all_ships, lasers)
            return

        # ── Target selection with team coordination ───────────────────────
        # Count how many living allies are currently engaging each enemy so
        # ships can spread fire across multiple targets instead of pile-driving one.
        target_counts: dict[int, int] = {}
        for ship in all_ships:
            if ship.team == self.team and ship.alive and ship._current_target is not None:
                tid = id(ship._current_target)
                target_counts[tid] = target_counts.get(tid, 0) + 1

        best_score  = float('inf')
        best_target = None
        for ship in all_ships:
            if ship is self or ship.team == self.team or not ship.alive:
                continue
            ex = ship.wx + ship.width  / 2
            ey = ship.wy + ship.height / 2
            d  = math.hypot(ex - cx, ey - cy)
            if d > self._detection_range:
                continue
            # Lower score = more desirable: closer enemies preferred but penalise
            # targets already being attacked by many allies
            ally_count = target_counts.get(id(ship), 0)
            score = d + ally_count * 260
            # If the fleet leader needs protection, prioritise threats near it
            if (self.fleet_leader is not None and self.fleet_leader is not self
                    and self.fleet_leader.alive
                    and getattr(self.fleet_leader, '_needs_defense', False)):
                lcx = self.fleet_leader.wx + self.fleet_leader.width  / 2
                lcy = self.fleet_leader.wy + self.fleet_leader.height / 2
                score -= max(0.0, (1000.0 - math.hypot(ex - lcx, ey - lcy)) * 0.8)
            if score < best_score:
                best_score  = score
                best_target = ship

        self._current_target = best_target
        self._has_target     = best_target is not None

        if best_target is None:
            self.combat_state = 'patrol'
            # Fleet cohesion: hold formation slot instead of wandering random waypoints
            if (self.fleet_leader is not None and self.fleet_leader is not self
                    and self.fleet_leader.alive):
                lcx = self.fleet_leader.wx + self.fleet_leader.width  / 2
                lcy = self.fleet_leader.wy + self.fleet_leader.height / 2
                self._movement_override = (lcx + self.fleet_offset[0],
                                           lcy + self.fleet_offset[1])
            else:
                if self.fleet_leader is not None and not self.fleet_leader.alive:
                    self.fleet_leader = None   # leader destroyed — go independent
                self._movement_override = None
            return

        # ── Set state and movement destination based on role ──────────────
        if self.role == 'flanker':
            self.combat_state       = 'flank'
            self._movement_override = self._calc_flank_pos(cx, cy, best_target)
        else:
            self.combat_state       = 'engage'
            self._movement_override = self._calc_intercept_pos(cx, cy, best_target)

        # ── Fleet cohesion: pull back if combat has dragged us too far ────
        if not self._should_hold_fire_course():
            if (self.fleet_leader is not None and self.fleet_leader is not self
                    and self.fleet_leader.alive):
                lcx = self.fleet_leader.wx + self.fleet_leader.width  / 2
                lcy = self.fleet_leader.wy + self.fleet_leader.height / 2
                slot_x = lcx + self.fleet_offset[0]
                slot_y = lcy + self.fleet_offset[1]
                if math.hypot(cx - slot_x, cy - slot_y) > self.fleet_stray_dist:
                    self._movement_override = (slot_x, slot_y)
            elif self.fleet_leader is not None and not self.fleet_leader.alive:
                self.fleet_leader = None
        elif self.fleet_leader is not None and not self.fleet_leader.alive:
            self.fleet_leader = None

        # ── Aim and fire ─────────────────────────────────────────────────
        self._aim_and_fire(dt, cx, cy, all_ships, lasers)

    # ── Tactic helpers ────────────────────────────────────────────────────────

    def _calc_intercept_pos(self, cx: float, cy: float, target) -> tuple[float, float]:
        """Predict where the target will be and return a cut-off position."""
        ex = target.wx + target.width  / 2
        ey = target.wy + target.height / 2
        d  = math.hypot(ex - cx, ey - cy)
        # Lead time: how long it takes us to close at max speed (scaled to converge, not overshoot)
        t  = d / max(1.0, self.max_speed) * 0.55
        return (ex + target.vx * t, ey + target.vy * t)

    def _calc_flank_pos(self, cx: float, cy: float, target) -> tuple[float, float]:
        """Return a position perpendicular to the target's movement direction."""
        ex = target.wx + target.width  / 2
        ey = target.wy + target.height / 2

        spd = math.hypot(target.vx, target.vy)
        if spd > 5.0:
            # Perpendicular to the target's travel direction
            nx, ny = target.vx / spd, target.vy / spd
        else:
            # Target is roughly stationary: use the line from self to target
            dx, dy = ex - cx, ey - cy
            d = math.hypot(dx, dy)
            if d > 0:
                nx, ny = dx / d, dy / d
            else:
                nx, ny = 1.0, 0.0

        # Rotate 90° to get the perpendicular, scaled by flank_side so each
        # ship consistently picks left or right and teams split naturally
        px = -ny * self._flank_side
        py =  nx * self._flank_side

        return (ex + px * FLANK_OFFSET, ey + py * FLANK_OFFSET)

    def _calc_retreat_pos(self, cx: float, cy: float, all_ships: list) -> tuple[float, float]:
        """Return a flee destination directly away from the nearest enemy."""
        nearest_enemy = None
        nearest_dist  = float('inf')
        for ship in all_ships:
            if ship.team == self.team or not ship.alive:
                continue
            ex = ship.wx + ship.width  / 2
            ey = ship.wy + ship.height / 2
            d  = math.hypot(ex - cx, ey - cy)
            if d < nearest_dist:
                nearest_dist  = d
                nearest_enemy = ship

        if nearest_enemy is None:
            return self.target  # no enemies: fall back to waypoint

        ex = nearest_enemy.wx + nearest_enemy.width  / 2
        ey = nearest_enemy.wy + nearest_enemy.height / 2
        dx, dy = cx - ex, cy - ey
        d = math.hypot(dx, dy)
        if d > 0:
            dx, dy = dx / d, dy / d
        else:
            dx, dy = 1.0, 0.0
        return (cx + dx * 900, cy + dy * 900)

    def _should_hold_fire_course(self) -> bool:
        """Return True while the destroyer is locking a target and should ignore course correction."""
        return (isinstance(self, Destroyer)
                and self._current_target is not None
                and self._charge > 0.0
                and self._cooldown <= 0.0)

    def _aim_and_fire(self, dt: float, cx: float, cy: float,
                      all_ships: list, lasers: list) -> None:
        """Aim weapons at the nearest in-range enemy and fire laser beams (instant hit)."""
        best_dist   = self.attack_range
        best_target = None
        for ship in all_ships:
            if ship is self or ship.team == self.team or not ship.alive:
                continue
            ex = ship.wx + ship.width  / 2
            ey = ship.wy + ship.height / 2
            d  = math.hypot(ex - cx, ey - cy)
            if d < best_dist:
                best_dist   = d
                best_target = ship

        self._has_target = best_target is not None

        # Target world centre (lasers are instant — aim directly, no lead needed)
        tx = ty = 0.0
        if best_target is not None:
            tx = best_target.wx + best_target.width  / 2
            ty = best_target.wy + best_target.height / 2

        L_w   = self.width  / 2
        W_w   = self.height / 2
        cos_a = math.cos(self.angle)
        sin_a = math.sin(self.angle)

        # ── Rotating turrets (capital ships, frigates) ────────────────────
        if self.gun_type in ('turret', 'both'):
            for turret in self.turrets:
                tlx = turret['lx'] * L_w
                tly = turret['ly'] * W_w
                twx = cx + tlx * cos_a - tly * sin_a
                twy = cy + tlx * sin_a + tly * cos_a

                turret['cooldown'] -= dt

                if best_target is not None:
                    desired = math.atan2(ty - twy, tx - twx)
                    diff    = self._angle_diff(desired, turret['angle'])
                    step    = math.copysign(min(abs(diff), TURRET_TURN_RATE * dt), diff)
                    raw     = turret['angle'] + step
                    turret['angle'] = math.atan2(math.sin(raw), math.cos(raw))

                    if turret['cooldown'] <= 0 and abs(diff) < 0.20:
                        turret['cooldown'] = self.fire_rate
                        best_target.try_take_damage(self.bullet_damage)
                        lasers.append(Laser(twx, twy, tx, ty, self.team))
                else:
                    turret['cooldown'] = max(0.0, turret['cooldown'])

        # ── Fixed forward guns (frigates, fighters) ───────────────────────
        if self.gun_type in ('fixed', 'both'):
            fire_aligned = False
            if best_target is not None:
                desired      = math.atan2(ty - cy, tx - cx)
                fire_aligned = abs(self._angle_diff(desired, self.angle)) < FIXED_GUN_ARC

            for gun in self.fixed_guns:
                gun['cooldown'] -= dt
                if fire_aligned and gun['cooldown'] <= 0:
                    tlx = gun['lx'] * L_w
                    tly = gun['ly'] * W_w
                    twx = cx + tlx * cos_a - tly * sin_a
                    twy = cy + tlx * sin_a + tly * cos_a
                    gun['cooldown'] = self.fire_rate
                    best_target.take_damage(self.bullet_damage)
                    lasers.append(Laser(twx, twy, tx, ty, self.team))
                elif not fire_aligned or best_target is None:
                    gun['cooldown'] = max(0.0, gun['cooldown'])

    # ── Shared helpers ────────────────────────────────────────────────────────

    @property
    def hit_chance(self) -> float:
        """Probability an incoming shot hits this ship; scales with hull width."""
        return min(0.92, max(0.22, self.width / 175.0))

    def take_damage(self, amount: int) -> None:
        self.hp -= amount
        if self.hp <= 0:
            self.hp    = 0
            self.alive = False

    def try_take_damage(self, amount: int) -> bool:
        """Roll hit chance before applying damage. Returns True if the shot hit."""
        if random.random() < self.hit_chance:
            self.take_damage(amount)
            return True
        return False

    def _emit_particles(self, dt: float) -> None:
        """Age existing particles and spawn new ones for thrust / dampeners."""
        alive = []
        for p in self._thruster_particles:
            p[4] += dt
            p[0] += p[2] * dt
            p[1] += p[3] * dt
            if p[4] < p[5]:
                alive.append(p)
        self._thruster_particles = alive

        cx = self.wx + self.width  / 2
        cy = self.wy + self.height / 2

        sp = math.hypot(self.vx, self.vy)

        if self._thrusting and sp > 5.0:
            # Exhaust streams opposite to the velocity vector (retrograde)
            retro_x = -self.vx / sp
            retro_y = -self.vy / sp
            for _ in range(2):
                ang   = math.atan2(retro_y, retro_x) + random.gauss(0, 0.28)
                spd   = random.uniform(sp * 0.40, sp * 0.95)
                max_a = random.uniform(0.15, 0.32)
                r0    = self.height * random.uniform(0.10, 0.30)
                self._thruster_particles.append([
                    cx + retro_x * self.width * 0.44,
                    cy + retro_y * self.width * 0.44,
                    math.cos(ang) * spd,
                    math.sin(ang) * spd,
                    0.0, max_a, r0, 0,
                ])

        if self._dampening and sp > 5.0:
            # Bow and side thrusters fire in the direction of motion to brake
            fwd_ang  = math.atan2(self.vy, self.vx)
            perp_ang = fwd_ang + math.pi / 2
            for sign in (1.0, -1.0):
                jx    = cx + math.cos(perp_ang) * self.height * 0.50 * sign
                jy    = cy + math.sin(perp_ang) * self.height * 0.50 * sign
                spd   = random.uniform(sp * 0.10, sp * 0.35)
                ang   = fwd_ang + random.gauss(0, 0.20)   # fire forward to brake
                max_a = random.uniform(0.10, 0.22)
                r0    = self.height * random.uniform(0.05, 0.15)
                self._thruster_particles.append([
                    jx, jy,
                    math.cos(ang) * spd,
                    math.sin(ang) * spd,
                    0.0, max_a, r0, 1,
                ])

    def _draw_particles(self, surface: pygame.Surface, camera) -> None:
        """Draw all live thruster / dampener particles under the hull."""
        sw = camera.screen_width
        sh = camera.screen_height
        for p in self._thruster_particles:
            t = max(0.0, 1.0 - p[4] / p[5])
            sx, sy = camera.world_to_screen(p[0], p[1])
            if sx < -20 or sx > sw + 20 or sy < -20 or sy > sh + 20:
                continue
            r = max(1, int(p[6] * camera.zoom * t))
            if p[7] == 0:   # exhaust: white-yellow → orange → dark
                col = (
                    min(255, int(220 * t + 35)),
                    int(150 * t * t),
                    int(20  * t * t * t),
                )
            else:            # dampener: cyan → blue → dark
                col = (
                    int(30  * t),
                    int(140 * t * t),
                    min(255, int(240 * t + 15)),
                )
            pygame.draw.circle(surface, col, (int(sx), int(sy)), r)

    def _turn_toward(self, target_angle: float, dt: float) -> None:
        diff = self._angle_diff(target_angle, self.angle)
        step = math.copysign(min(abs(diff), self.turn_rate * dt), diff)
        raw  = self.angle + step
        self.angle = math.atan2(math.sin(raw), math.cos(raw))

    @staticmethod
    def _angle_diff(target: float, current: float) -> float:
        """Shortest signed angle from current to target in [-π, π]."""
        return (target - current + math.pi) % (2 * math.pi) - math.pi

    # ── Rendering ─────────────────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, camera) -> None:
        if not self.alive or not camera.is_visible(self.world_rect):
            return

        cx, cy = camera.world_to_screen(
            self.wx + self.width  / 2,
            self.wy + self.height / 2,
        )

        cos_a = math.cos(self.angle)
        sin_a = math.sin(self.angle)
        L = self.width  / 2 * camera.zoom
        W = self.height / 2 * camera.zoom

        # Ship hull polygon
        local_pts = [
            ( L,        0.0    ),
            ( L * 0.25, W      ),
            (-L,        W * 0.6),
            (-L,       -W * 0.6),
            ( L * 0.25,-W      ),
        ]

        def to_screen(lx, ly):
            return (lx * cos_a - ly * sin_a + cx,
                    lx * sin_a + ly * cos_a + cy)

        self._draw_particles(surface, camera)

        screen_pts = [to_screen(lx, ly) for lx, ly in local_pts]
        pygame.draw.polygon(surface, self.color, screen_pts)
        pygame.draw.polygon(surface, (255, 255, 255), screen_pts, 1)

        # Combat-state indicator dot on the nose of the ship
        state_color = self._STATE_COLORS.get(self.combat_state, (128, 128, 128))
        ind_x = int(cx + cos_a * (L * 0.65))
        ind_y = int(cy + sin_a * (L * 0.65))
        pygame.draw.circle(surface, (0, 0, 0),    (ind_x, ind_y), 4)
        pygame.draw.circle(surface, state_color,  (ind_x, ind_y), 3)

        # Weapons
        gun_col = (200, 200, 200) if self._has_target else (130, 130, 130)
        # Rotating turrets — capital ships and frigates
        if self.gun_type in ('turret', 'both'):
            base_r     = max(3, int(W * 0.35))
            barrel_len = max(int(L * 0.65), 10)
            barrel_w   = max(2, int(W * 0.18))
            for turret in self.turrets:
                tlx_s = turret['lx'] * L
                tly_s = turret['ly'] * W
                tscx  = cx + tlx_s * cos_a - tly_s * sin_a
                tscy  = cy + tlx_s * sin_a + tly_s * cos_a
                pygame.draw.circle(surface, (60, 60, 60), (int(tscx), int(tscy)), base_r + 1)
                pygame.draw.circle(surface, gun_col, (int(tscx), int(tscy)), base_r)
                tx_end = tscx + math.cos(turret['angle']) * barrel_len
                ty_end = tscy + math.sin(turret['angle']) * barrel_len
                pygame.draw.line(surface, gun_col,
                                 (int(tscx), int(tscy)), (int(tx_end), int(ty_end)), barrel_w)
        # Fixed forward gun barrels — frigates and fighters
        if self.gun_type in ('fixed', 'both'):
            barrel_len_f = max(int(L * 0.55), 6)
            barrel_w_f   = max(1, int(W * 0.12))
            for gun in self.fixed_guns:
                glx_s = gun['lx'] * L
                gly_s = gun['ly'] * W
                gscx  = cx + glx_s * cos_a - gly_s * sin_a
                gscy  = cy + glx_s * sin_a + gly_s * cos_a
                ge_x  = gscx + cos_a * barrel_len_f
                ge_y  = gscy + sin_a * barrel_len_f
                pygame.draw.line(surface, gun_col,
                                 (int(gscx), int(gscy)), (int(ge_x), int(ge_y)), barrel_w_f)

        # Health bar (only when damaged)
        if self.hp < self.max_hp:
            half_diag = math.hypot(L, W)
            bar_w  = max(20, int(L * 2.2))
            bar_h  = 4
            bar_x  = int(cx - bar_w // 2)
            bar_y  = int(cy - half_diag - 9)
            fill_w = int(bar_w * self.hp / self.max_hp)
            pygame.draw.rect(surface, (120, 0,   0), (bar_x, bar_y, bar_w,  bar_h))
            pygame.draw.rect(surface, (0,   210, 60), (bar_x, bar_y, fill_w, bar_h))
            pygame.draw.rect(surface, (200, 200, 200), (bar_x, bar_y, bar_w, bar_h), 1)


# ── Fighter ───────────────────────────────────────────────────────────────────

_FIGHTER_COLORS = [(0, 210, 230), (240, 180, 20)]   # cyan / gold per team

class Fighter(AICharacter):
    """
    Tiny interceptor deployed by Carriers.
    Very fast and agile, but fragile and lightly armed.
    """

    LAUNCH_DURATION = 2.2   # seconds for catapult roll and climb-out
    DOCK_RADIUS     = 85.0  # world units from carrier centre to trigger docking
    RETURN_IDLE_T   = 9.0   # seconds without a target before starting return approach

    def __init__(self, wx: float, wy: float, waypoints: list[tuple[float, float]],
                 team: int, home_carrier=None):
        w = random.randint(20, 30)
        h = random.randint(10, 16)
        super().__init__(wx, wy, waypoints, team, _w=w, _h=h)

        # Override all stats — fighters are extreme in every direction
        self.max_speed     = random.uniform(720, 900)
        self.thrust        = random.uniform(340, 430)
        self.turn_rate     = random.uniform(5.0, 7.0)
        self.fire_rate     = random.uniform(0.7, 1.2)
        self.bullet_damage = random.randint(2, 4)
        self.max_hp        = random.randint(10, 20)
        self.hp            = self.max_hp
        self.color         = _FIGHTER_COLORS[team]
        self.role          = 'attacker'   # fighters always push forward
        self.home_carrier  = home_carrier

        # Launch / return state
        self._launch_t     = self.LAUNCH_DURATION
        self._launch_angle = home_carrier.angle if home_carrier is not None else self.angle
        self._returning    = False   # True while flying back to dock on the carrier
        self._idle_t       = 0.0    # seconds elapsed with no combat target

        # Fixed forward wing-mounted guns — no rotating turret
        self.gun_type   = 'fixed'
        self.turrets    = []
        self.fixed_guns = [
            {'lx': 0.15, 'ly': -0.7, 'cooldown': random.uniform(0, self.fire_rate)},
            {'lx': 0.15, 'ly':  0.7, 'cooldown': random.uniform(0, self.fire_rate)},
        ]

    def update(self, dt: float) -> None:
        if self._launch_t > 0:
            # Catapult roll: linear acceleration from 0 → max_speed along carrier heading
            self._launch_t -= dt
            progress      = 1.0 - max(0.0, self._launch_t) / self.LAUNCH_DURATION
            self.angle    = self._launch_angle
            self.vx       = math.cos(self._launch_angle) * self.max_speed * progress
            self.vy       = math.sin(self._launch_angle) * self.max_speed * progress
            self.wx      += self.vx * dt
            self.wy      += self.vy * dt
            self._thrusting = True
        elif self._returning and self.home_carrier is not None and self.home_carrier.alive:
            # Dock when centre of fighter reaches DOCK_RADIUS of carrier centre
            hcx = self.home_carrier.wx + self.home_carrier.width  / 2
            hcy = self.home_carrier.wy + self.home_carrier.height / 2
            fx  = self.wx + self.width  / 2
            fy  = self.wy + self.height / 2
            if math.hypot(fx - hcx, fy - hcy) < self.DOCK_RADIUS:
                self.alive = False   # docked — carrier draw() will show it as parked
                return
            super().update(dt)
        else:
            if self._returning:
                self._returning = False   # carrier is gone; fight independently
            super().update(dt)

    def update_combat(self, dt: float, all_ships: list, lasers: list) -> None:
        if self._launch_t > 0:
            return   # weapons hold during launch roll

        # ── Returning to carrier ──────────────────────────────────────────────
        if self._returning:
            if self.home_carrier is None or not self.home_carrier.alive:
                self._returning = False   # carrier destroyed; fight on
            else:
                hcx   = self.home_carrier.wx + self.home_carrier.width  / 2
                hcy   = self.home_carrier.wy + self.home_carrier.height / 2
                cos_a = math.cos(self.home_carrier.angle)
                sin_a = math.sin(self.home_carrier.angle)
                # Aim for the carrier bow so the approach looks like a landing
                self._movement_override = (
                    hcx + cos_a * self.home_carrier.width * 0.40,
                    hcy + sin_a * self.home_carrier.width * 0.40,
                )
                self.combat_state = 'patrol'
            return

        # ── Normal combat (inherited) ─────────────────────────────────────────
        super().update_combat(dt, all_ships, lasers)

        # ── Idle timer: return to carrier when no enemies for a while ─────────
        if (self._current_target is None
                and self.home_carrier is not None
                and self.home_carrier.alive):
            self._idle_t += dt
            if self._idle_t >= self.RETURN_IDLE_T:
                self._returning = True
                self._idle_t    = 0.0
        else:
            self._idle_t = 0.0

    def draw(self, surface: pygame.Surface, camera) -> None:
        if not self.alive or not camera.is_visible(self.world_rect):
            return

        cx, cy = camera.world_to_screen(
            self.wx + self.width  / 2,
            self.wy + self.height / 2,
        )

        z     = camera.zoom
        L     = self.width  / 2 * z
        W     = self.height / 2 * z
        cos_a = math.cos(self.angle)
        sin_a = math.sin(self.angle)

        def to_screen(lx, ly):
            return (lx * cos_a - ly * sin_a + cx,
                    lx * sin_a + ly * cos_a + cy)

        # Delta-wing arrowhead hull
        local_pts = [
            ( L,      0.0  ),   # nose
            ( 0.0,    W    ),   # starboard wing tip
            (-L * 0.5, W * 0.3),
            (-L,       0.0 ),   # tail
            (-L * 0.5,-W * 0.3),
            ( 0.0,   -W    ),   # port wing tip
        ]
        self._draw_particles(surface, camera)

        pts = [to_screen(lx, ly) for lx, ly in local_pts]
        pygame.draw.polygon(surface, self.color, pts)
        pygame.draw.polygon(surface, (255, 255, 255), pts, 1)

        # Fixed forward wing guns pointing in ship direction
        gun_col    = (220, 220, 220) if self._has_target else (110, 110, 110)
        barrel_len = max(int(L * 0.5), 3)
        for gun in self.fixed_guns:
            glx_s = gun['lx'] * L
            gly_s = gun['ly'] * W
            gscx  = cx + glx_s * cos_a - gly_s * sin_a
            gscy  = cy + glx_s * sin_a + gly_s * cos_a
            ge_x  = gscx + cos_a * barrel_len
            ge_y  = gscy + sin_a * barrel_len
            pygame.draw.line(surface, gun_col,
                             (int(gscx), int(gscy)), (int(ge_x), int(ge_y)), 1)

        # State dot (doubles as the "cockpit" mark)
        state_color = self._STATE_COLORS.get(self.combat_state, (128, 128, 128))
        pygame.draw.circle(surface, state_color, (int(cx), int(cy)), max(2, int(W * 0.45)))

        # Health bar
        if self.hp < self.max_hp:
            half_diag = math.hypot(L, W)
            bar_w  = max(10, int(L * 1.8))
            bar_h  = 2
            bar_x  = int(cx - bar_w // 2)
            bar_y  = int(cy - half_diag - 5)
            fill_w = int(bar_w * self.hp / self.max_hp)
            pygame.draw.rect(surface, (120, 0,  0), (bar_x, bar_y, bar_w,  bar_h))
            pygame.draw.rect(surface, (0, 210, 60), (bar_x, bar_y, fill_w, bar_h))


# ── Carrier ───────────────────────────────────────────────────────────────────

_CARRIER_COLORS    = [(25, 55, 140), (140, 20, 20)]   # dark navy / dark crimson
_DESTROYER_COLORS  = [(45, 75, 160), (160, 40, 40)]  # steel blue / steel red

class Carrier(AICharacter):
    """
    Massive ship that stays behind the front line and deploys Fighter squadrons.
    Armed only with light AA guns (short range, fast fire, low damage).
    Relies on capital ships and frigates for heavy combat.
    Deploys fighters both proactively and defensively when enemies are detected.
    """

    MAX_FIGHTERS    = 5      # maximum active fighters per carrier
    DEPLOY_INTERVAL = 10.0   # seconds between fighter deployments

    # Six possible AA turret positions around the hull perimeter (lx_frac, ly_frac)
    _AA_POSITIONS = [
        ( 0.55, -0.45), ( 0.55,  0.45),   # fore port / starboard
        (-0.05, -0.52), (-0.05,  0.52),   # mid  port / starboard
        (-0.65, -0.42), (-0.65,  0.42),   # aft  port / starboard
    ]

    def __init__(self, wx: float, wy: float, waypoints: list[tuple[float, float]],
                 team: int):
        w = random.randint(180, 240)
        h = random.randint(80, 120)
        super().__init__(wx, wy, waypoints, team, _w=w, _h=h)

        # Override stats: slow, tanky, light AA armament
        self.max_speed     = random.uniform(100, 155)
        self.thrust        = random.uniform(50, 80)
        self.turn_rate     = random.uniform(0.4, 0.85)
        self.fire_rate     = random.uniform(0.4, 0.65)   # AA fires rapidly...
        self.bullet_damage = random.randint(2, 4)          # ...but tickles
        self.max_hp        = random.randint(220, 350)
        self.hp            = self.max_hp
        self.attack_range  = AA_RANGE                      # short AA range only
        self.color         = _CARRIER_COLORS[team]
        self.role          = 'carrier'

        # Build AA turrets (4-6 positions around the hull)
        num_aa = random.choice([4, 4, 5, 6])
        chosen = random.sample(self._AA_POSITIONS, num_aa)
        self.turrets = [
            {
                'lx': lx, 'ly': ly,
                'angle':    random.uniform(0, math.tau),
                'cooldown': random.uniform(0, self.fire_rate),
            }
            for lx, ly in chosen
        ]

        # Fighter management
        self._deploy_timer    = random.uniform(0, self.DEPLOY_INTERVAL * 0.5)
        self._active_fighters: list = []   # references tracked for headcount
        self._spawn_queue:    list  = []   # (wx, wy, team) tuples; processed by main.py
        self._needs_defense   = False      # True when enemies are dangerously close

    # ── Combat override ───────────────────────────────────────────────────────

    def update_combat(self, dt: float, all_ships: list, lasers: list) -> None:
        if not self.alive:
            return

        cx = self.wx + self.width  / 2
        cy = self.wy + self.height / 2

        # Separation — carriers need more personal space than frigates
        for ship in all_ships:
            if ship is self or ship.team != self.team or not ship.alive:
                continue
            ox = ship.wx + ship.width  / 2
            oy = ship.wy + ship.height / 2
            d  = math.hypot(ox - cx, oy - cy)
            if 0 < d < SEPARATION_DIST * 1.6:
                strength = (SEPARATION_DIST * 1.6 - d) / (SEPARATION_DIST * 1.6) * SEPARATION_FORCE
                self._sep_ax += (cx - ox) / d * strength
                self._sep_ay += (cy - oy) / d * strength

        # Find nearest enemy (used for movement and deployment decisions)
        nearest_enemy = None
        nearest_dist  = float('inf')
        for ship in all_ships:
            if ship.team == self.team or not ship.alive:
                continue
            ex = ship.wx + ship.width  / 2
            ey = ship.wy + ship.height / 2
            d  = math.hypot(ex - cx, ey - cy)
            if d < nearest_dist:
                nearest_dist  = d
                nearest_enemy = ship

        # Signal allied ships when the carrier is threatened
        SAFE_DIST = ATTACK_RANGE * 1.8
        self._needs_defense = (nearest_enemy is not None and nearest_dist < SAFE_DIST)

        # Movement: hang back at a safe distance — never charge the front line
        if nearest_enemy is not None and nearest_dist < SAFE_DIST:
            self.combat_state = 'retreat'
            ex = nearest_enemy.wx + nearest_enemy.width  / 2
            ey = nearest_enemy.wy + nearest_enemy.height / 2
            dx, dy = cx - ex, cy - ey
            d = math.hypot(dx, dy)
            if d > 0:
                dx, dy = dx / d, dy / d
            self._movement_override = (cx + dx * 700, cy + dy * 700)
        else:
            self.combat_state       = 'patrol'
            self._movement_override = None

        # AA guns fire at enemies that get within AA_RANGE
        self._aim_and_fire(dt, cx, cy, all_ships, lasers)

        # ── Fighter deployment ─────────────────────────────────────────────
        # Prune dead fighters from the active list
        self._active_fighters = [f for f in self._active_fighters if f.alive]
        live_count = len(self._active_fighters)

        enemy_detected    = nearest_enemy is not None and nearest_dist < ATTACK_RANGE * 2.2
        under_direct_fire = nearest_dist < AA_RANGE * 1.5

        self._deploy_timer -= dt

        if enemy_detected and live_count < self.MAX_FIGHTERS:
            # Emergency scramble: bypass timer when enemy is dangerously close
            # and we have fewer than half our fighters up
            if under_direct_fire and live_count < self.MAX_FIGHTERS // 2:
                self._queue_fighter(cx, cy)
                self._deploy_timer = self.DEPLOY_INTERVAL * 0.4

            elif self._deploy_timer <= 0:
                self._queue_fighter(cx, cy)
                self._deploy_timer = self.DEPLOY_INTERVAL

    def _queue_fighter(self, cx: float, cy: float) -> None:
        """Push a spawn request onto the queue; main.py creates the Fighter."""
        # Spawn at the carrier bow so the launch animation slides off the deck
        cos_a = math.cos(self.angle)
        sin_a = math.sin(self.angle)
        bow_x = cx + cos_a * (self.width * 0.42)
        bow_y = cy + sin_a * (self.width * 0.42)
        self._spawn_queue.append((bow_x, bow_y, self.team))

    # ── Rendering override ────────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, camera) -> None:
        if not self.alive or not camera.is_visible(self.world_rect):
            return

        cx, cy = camera.world_to_screen(
            self.wx + self.width  / 2,
            self.wy + self.height / 2,
        )

        z     = camera.zoom
        L     = self.width  / 2 * z
        W     = self.height / 2 * z
        cos_a = math.cos(self.angle)
        sin_a = math.sin(self.angle)

        def to_screen(lx, ly):
            return (lx * cos_a - ly * sin_a + cx,
                    lx * sin_a + ly * cos_a + cy)

        self._draw_particles(surface, camera)

        # Hull — long rectangular carrier silhouette
        hull_pts = [
            ( L,        W * 0.20),
            ( L,       -W * 0.20),
            ( L * 0.78, -W * 0.58),
            (-L * 0.75, -W * 0.62),
            (-L,        -W * 0.46),
            (-L,         W * 0.46),
            (-L * 0.75,  W * 0.62),
            ( L * 0.78,  W * 0.58),
        ]
        hull_screen = [to_screen(lx, ly) for lx, ly in hull_pts]
        pygame.draw.polygon(surface, self.color, hull_screen)
        pygame.draw.polygon(surface, (200, 200, 200), hull_screen, 1)

        # Flight deck — lighter strip running the length of the ship
        deck_color = (
            min(255, self.color[0] + 35),
            min(255, self.color[1] + 35),
            min(255, self.color[2] + 35),
        )
        deck_pts = [
            to_screen( L * 0.88,  W * 0.10),
            to_screen(-L * 0.82,  W * 0.10),
            to_screen(-L * 0.82, -W * 0.08),
            to_screen( L * 0.88, -W * 0.08),
        ]
        pygame.draw.polygon(surface, deck_color, deck_pts)

        # Parked fighters on the flight deck
        in_hangar = max(0, self.MAX_FIGHTERS - sum(1 for f in self._active_fighters if f.alive))
        if in_hangar > 0 and L > 10:
            fw    = max(3, int(L * 0.090))   # fighter half-length in screen px
            fh    = max(2, int(fw * 0.48))   # fighter half-width
            f_col = _FIGHTER_COLORS[self.team]
            x_min_f = -0.58
            x_max_f =  0.68
            step_f  = (x_max_f - x_min_f) / max(1, self.MAX_FIGHTERS - 1)
            for s in range(in_hangar):
                slot_lx = (x_min_f + s * step_f) * L
                slot_ly = 0.01 * W
                fsx = cx + slot_lx * cos_a - slot_ly * sin_a
                fsy = cy + slot_lx * sin_a + slot_ly * cos_a
                # Tiny arrowhead pointing in carrier heading direction
                nose = (fsx + cos_a * fw,                       fsy + sin_a * fw)
                wl   = (fsx - cos_a * fw * 0.55 + sin_a * fh,   fsy - sin_a * fw * 0.55 - cos_a * fh)
                wr   = (fsx - cos_a * fw * 0.55 - sin_a * fh,   fsy - sin_a * fw * 0.55 + cos_a * fh)
                pygame.draw.polygon(surface, f_col, [nose, wl, wr])

        # Island superstructure (starboard side)
        isl_color = (
            min(255, self.color[0] + 55),
            min(255, self.color[1] + 55),
            min(255, self.color[2] + 55),
        )
        isl_pts = [
            to_screen( L * 0.25,  W * 0.48),
            to_screen(-L * 0.10,  W * 0.48),
            to_screen(-L * 0.10,  W * 0.65),
            to_screen( L * 0.25,  W * 0.65),
        ]
        pygame.draw.polygon(surface, isl_color, isl_pts)
        pygame.draw.polygon(surface, (220, 220, 220), isl_pts, 1)

        # AA turrets (small, many)
        aa_base_r   = max(2, int(W * 0.18))
        aa_barrel   = max(int(L * 0.22), 6)
        aa_col      = (190, 220, 190) if self._has_target else (120, 140, 120)
        for turret in self.turrets:
            tscx = cx + (turret['lx'] * L) * cos_a - (turret['ly'] * W) * sin_a
            tscy = cy + (turret['lx'] * L) * sin_a + (turret['ly'] * W) * cos_a
            pygame.draw.circle(surface, (40, 40, 40),  (int(tscx), int(tscy)), aa_base_r + 1)
            pygame.draw.circle(surface, aa_col,         (int(tscx), int(tscy)), aa_base_r)
            tx_end = tscx + math.cos(turret['angle']) * aa_barrel
            ty_end = tscy + math.sin(turret['angle']) * aa_barrel
            pygame.draw.line(surface, aa_col, (int(tscx), int(tscy)), (int(tx_end), int(ty_end)), 1)

        # Combat-state dot
        state_color = self._STATE_COLORS.get(self.combat_state, (128, 128, 128))
        pygame.draw.circle(surface, (0, 0, 0),   (int(cx), int(cy)), 5)
        pygame.draw.circle(surface, state_color, (int(cx), int(cy)), 4)

        # Health bar
        if self.hp < self.max_hp:
            half_diag = math.hypot(L, W)
            bar_w  = max(30, int(L * 2.4))
            bar_h  = 5
            bar_x  = int(cx - bar_w // 2)
            bar_y  = int(cy - half_diag - 10)
            fill_w = int(bar_w * self.hp / self.max_hp)
            pygame.draw.rect(surface, (120, 0,   0), (bar_x, bar_y, bar_w,  bar_h))
            pygame.draw.rect(surface, (0,  210, 60), (bar_x, bar_y, fill_w, bar_h))
            pygame.draw.rect(surface, (200, 200, 200), (bar_x, bar_y, bar_w, bar_h), 1)


# ── Destroyer ─────────────────────────────────────────────────────────────────

class Destroyer(AICharacter):
    """
    Heavy warship armed with a single devastating fixed main cannon.

    The weapon charges over CHARGE_TIME seconds while the ship holds its aim
    on a target — a glowing energy orb grows at the muzzle tip.  When fully
    charged, it fires a beam thick enough to destroy any capital ship in one
    hit.  Destroyers must turn their entire hull to aim, making flanking them
    the primary counter.

    Combat role: anti-capital sniper.  Devastating on a firing line;
    vulnerable when caught out of position or circled by fast frigates.
    """

    CHARGE_TIME   = 1.0         # seconds of continuous aim-lock required to fire
    COOLDOWN_TIME = 4.0         # shorter cooldown; total cycle is roughly 3x less frequent than other ships
    CANNON_RANGE  = ATTACK_RANGE * 6.0  # world units — three times the range of standard ships
    CANNON_ARC    = 0.10        # half firing arc in radians (~5.7°)
    CANNON_DAMAGE = 200         # one-shots any capital ship

    def __init__(self, wx: float, wy: float, waypoints: list, team: int = 0):
        w = random.randint(130, 165)
        h = random.randint(45,  62)
        super().__init__(wx, wy, waypoints, team, _w=w, _h=h)

        self.max_speed  = random.uniform(220, 310)
        self.thrust     = random.uniform(110, 150)
        self.turn_rate  = random.uniform(0.9, 1.5)
        self.max_hp     = random.randint(120, 200)
        self.hp         = self.max_hp
        self.color      = _DESTROYER_COLORS[team]
        self.role       = 'attacker'

        # No inherited turrets or fixed guns — single custom cannon
        self.gun_type         = 'destroyer'
        self.turrets          = []
        self.fixed_guns       = []
        self._detection_range = self.CANNON_RANGE * 1.5  # sees much further than standard ships

        self._charge     = 0.0   # charge accumulated (0 → CHARGE_TIME)
        self._cooldown   = 0.0   # post-fire cooldown countdown
        self._fire_flash = 0.0   # brief muzzle flash after firing

    @property
    def _charge_frac(self) -> float:
        return self._charge / self.CHARGE_TIME

    def take_damage(self, amount: int) -> None:
        super().take_damage(amount)
        self._charge = 0.0   # any hit breaks the charge

    def _aim_and_fire(self, dt: float, cx: float, cy: float,
                      all_ships: list, lasers: list) -> None:
        self._fire_flash = max(0.0, self._fire_flash - dt)
        self._cooldown   = max(0.0, self._cooldown   - dt)

        # ── Main cannon — prefers large ships (carriers > capitals > frigates) ──
        best_score  = float('inf')
        best_target = None
        for ship in all_ships:
            if ship is self or ship.team == self.team or not ship.alive:
                continue
            ex = ship.wx + ship.width  / 2
            ey = ship.wy + ship.height / 2
            d  = math.hypot(ex - cx, ey - cy)
            if d > self.CANNON_RANGE:
                continue
            # Lower score = higher priority; big ships get a large bonus
            if isinstance(ship, Carrier):
                size_bonus = 4000
            elif ship.width >= 88:
                size_bonus = 2000
            else:
                size_bonus = 0
            score = d - size_bonus
            if score < best_score:
                best_score  = score
                best_target = ship

        self._has_target = best_target is not None

        if best_target is None or self._cooldown > 0 or self.combat_state == 'retreat':
            self._charge = max(0.0, self._charge - dt * 0.5)
        else:
            tx      = best_target.wx + best_target.width  / 2
            ty      = best_target.wy + best_target.height / 2
            desired = math.atan2(ty - cy, tx - cx)
            in_arc  = abs(self._angle_diff(desired, self.angle)) < self.CANNON_ARC

            if in_arc:
                self._charge = min(self.CHARGE_TIME, self._charge + dt)
                if self._charge >= self.CHARGE_TIME:
                    # ── FIRE ──────────────────────────────────────────────
                    self._charge     = 0.0
                    self._cooldown   = self.COOLDOWN_TIME
                    self._fire_flash = 0.40
                    best_target.try_take_damage(self.CANNON_DAMAGE)
                    mx = cx + math.cos(self.angle) * (self.width * 0.625)
                    my = cy + math.sin(self.angle) * (self.width * 0.625)
                    lasers.append(DestroyerBeam(mx, my, tx, ty, self.team))
            else:
                self._charge = max(0.0, self._charge - dt * 2.5)

    def draw(self, surface: pygame.Surface, camera) -> None:
        if not self.alive or not camera.is_visible(self.world_rect):
            return

        cx, cy = camera.world_to_screen(
            self.wx + self.width  / 2,
            self.wy + self.height / 2,
        )
        z     = camera.zoom
        L     = self.width  / 2 * z
        W     = self.height / 2 * z
        cos_a = math.cos(self.angle)
        sin_a = math.sin(self.angle)

        def to_screen(lx, ly):
            return (lx * cos_a - ly * sin_a + cx,
                    lx * sin_a + ly * cos_a + cy)

        self._draw_particles(surface, camera)

        # Hull — sharp, angular destroyer silhouette
        hull_pts = [
            ( L,          0.0    ),   # prow tip
            ( L * 0.60,   W      ),
            (-L * 0.55,   W * 0.70),
            (-L,          W * 0.40),
            (-L,         -W * 0.40),
            (-L * 0.55,  -W * 0.70),
            ( L * 0.60,  -W      ),
        ]
        screen_pts = [to_screen(lx, ly) for lx, ly in hull_pts]
        pygame.draw.polygon(surface, self.color, screen_pts)
        pygame.draw.polygon(surface, (190, 200, 220), screen_pts, 1)

        # Main cannon barrel — long spine along the centreline
        barrel_base = to_screen(L * 0.10, 0.0)
        barrel_tip  = to_screen(L * 1.25, 0.0)
        bw = max(3, int(W * 0.26))
        pygame.draw.line(surface, (130, 145, 165),
                         (int(barrel_base[0]), int(barrel_base[1])),
                         (int(barrel_tip[0]),  int(barrel_tip[1])), bw)
        # Barrel highlight stripe
        pygame.draw.line(surface, (190, 200, 215),
                         (int(barrel_base[0]), int(barrel_base[1])),
                         (int(barrel_tip[0]),  int(barrel_tip[1])), max(1, bw // 3))

        # Muzzle position in screen space (matches _aim_and_fire world muzzle)
        muzzle_sx = cx + cos_a * L * 1.25
        muzzle_sy = cy + sin_a * L * 1.25

        # ── Cooldown heat animation ────────────────────────────────────────
        if self._cooldown > 0.0:
            ct = self._cooldown / self.COOLDOWN_TIME   # 1=just fired, 0=ready
            # Barrel glows orange-red and fades to cool grey
            heat_r = 255
            heat_g = int(140 * (1.0 - ct))
            heat_b = 0
            heat_col  = (heat_r, heat_g, heat_b)
            heat_glow = (heat_r // 4, heat_g // 4, 0)
            glow_w = bw + max(2, int(bw * 1.2 * ct))
            pygame.draw.line(surface, heat_glow,
                             (int(barrel_base[0]), int(barrel_base[1])),
                             (int(barrel_tip[0]),  int(barrel_tip[1])), glow_w)
            pygame.draw.line(surface, heat_col,
                             (int(barrel_base[0]), int(barrel_base[1])),
                             (int(barrel_tip[0]),  int(barrel_tip[1])), bw)
            # Heat shimmer dot at the breech
            breech_sx = cx + cos_a * L * 0.10
            breech_sy = cy + sin_a * L * 0.10
            pygame.draw.circle(surface, heat_col,
                               (int(breech_sx), int(breech_sy)), max(2, int(bw * ct)))

        # ── Charging animation ─────────────────────────────────────────────
        f = self._charge_frac
        if f > 0.0:
            # Colour ramp: dark purple-blue → bright cyan-white
            r_c = int(55  * (1.0 - f))
            g_c = int(200 * f)
            b_c = 255
            charge_col = (r_c, g_c, b_c)

            # Fast pulse when nearly charged (last 20%)
            pulse = 1.0
            if f > 0.80:
                t_ms  = pygame.time.get_ticks()
                pulse = 0.76 + 0.24 * math.sin(t_ms * 0.027)

            glow_r = max(4, int(W * 1.7 * f * pulse))
            core_r = max(2, int(W * 0.85 * f * pulse))

            # Dim outer halo
            pygame.draw.circle(surface, (r_c // 5, g_c // 5, b_c // 5),
                               (int(muzzle_sx), int(muzzle_sy)), glow_r)
            # Main charge orb
            pygame.draw.circle(surface, charge_col,
                               (int(muzzle_sx), int(muzzle_sy)), core_r)
            # Bright inner core
            if core_r > 3:
                pygame.draw.circle(surface, (210, 240, 255),
                                   (int(muzzle_sx), int(muzzle_sy)), core_r // 2)

            # Energy rings that appear in the final 18% of charge
            if f > 0.82:
                t_ms = pygame.time.get_ticks()
                for i in range(2):
                    rr = glow_r + 5 + i * 7 + int(3 * math.sin(t_ms * 0.024 + i * 1.9))
                    pygame.draw.circle(surface, (r_c // 3, g_c // 3, b_c // 3),
                                       (int(muzzle_sx), int(muzzle_sy)), rr, 1)

        # Post-fire muzzle flash
        if self._fire_flash > 0.0:
            ft   = self._fire_flash / 0.40
            fr   = max(5, int(W * 2.4 * ft))
            fcol = (170, 225, 255) if self.team == 0 else (255, 205, 150)
            pygame.draw.circle(surface, fcol,
                               (int(muzzle_sx), int(muzzle_sy)), fr)
            pygame.draw.circle(surface, (255, 255, 255),
                               (int(muzzle_sx), int(muzzle_sy)), max(2, fr // 3))

        # Combat-state dot on the hull spine
        state_color = self._STATE_COLORS.get(self.combat_state, (128, 128, 128))
        ind_x = int(cx + cos_a * L * 0.45)
        ind_y = int(cy + sin_a * L * 0.45)
        pygame.draw.circle(surface, (0, 0, 0),   (ind_x, ind_y), 5)
        pygame.draw.circle(surface, state_color, (ind_x, ind_y), 4)

        # Health bar
        if self.hp < self.max_hp:
            half_diag = math.hypot(L, W)
            bar_w  = max(25, int(L * 2.3))
            bar_h  = 4
            bar_x  = int(cx - bar_w // 2)
            bar_y  = int(cy - half_diag - 9)
            fill_w = int(bar_w * self.hp / self.max_hp)
            pygame.draw.rect(surface, (120, 0,   0), (bar_x, bar_y, bar_w,  bar_h))
            pygame.draw.rect(surface, (0,  210, 60), (bar_x, bar_y, fill_w, bar_h))
            pygame.draw.rect(surface, (200, 200, 200), (bar_x, bar_y, bar_w, bar_h), 1)
