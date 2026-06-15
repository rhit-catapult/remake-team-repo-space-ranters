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

# Combat constants shared by all ships
ATTACK_RANGE     = 600.0   # world units — turret engagement range
FIRE_RATE        = 2.0     # seconds between shots
TURRET_TURN_RATE = 3.5     # radians / second — how fast the turret rotates


class Bullet:
    """A projectile fired by a ship turret."""

    SPEED    = 380.0   # world units / second
    DAMAGE   = 10
    LIFETIME = 2.2     # seconds (≈ 836 world-unit range)
    RADIUS   = 3

    _TEAM_COLORS = [(120, 180, 255), (255, 100, 80)]

    def __init__(self, wx: float, wy: float, angle: float, team: int):
        self.wx       = wx
        self.wy       = wy
        self.vx       = math.cos(angle) * self.SPEED
        self.vy       = math.sin(angle) * self.SPEED
        self.team     = team
        self.lifetime = self.LIFETIME
        self.alive    = True

    @property
    def world_rect(self) -> pygame.Rect:
        r = self.RADIUS
        return pygame.Rect(int(self.wx) - r, int(self.wy) - r, r * 2, r * 2)

    def update(self, dt: float):
        self.wx += self.vx * dt
        self.wy += self.vy * dt
        self.lifetime -= dt
        if self.lifetime <= 0:
            self.alive = False

    def draw(self, surface: pygame.Surface, camera) -> None:
        if not camera.is_visible(self.world_rect):
            return
        sx, sy = camera.world_to_screen(self.wx, self.wy)
        color = self._TEAM_COLORS[self.team]
        pygame.draw.circle(surface, color,         (int(sx), int(sy)), self.RADIUS)
        pygame.draw.circle(surface, (255, 255, 255), (int(sx), int(sy)), max(1, self.RADIUS - 1))


class AICharacter(Entity):
    """
    Spaceship AI flying between waypoints with vacuum-inertia physics.
    Ships belong to a team and fire a turret at the nearest enemy in range.

    Movement phases:
      Cruise  — turn toward waypoint, thrust forward when aligned.
      Braking — turn to face retrograde (opposite velocity), thrust to slow down.
    """

    TURN_RATE   = 2.5    # radians / second
    THRUST      = 85.0   # world units / second²
    MAX_SPEED   = 120.0  # world units / second
    DRAG        = 0.97   # speed multiplier / second
    DECEL_DIST  = 250.0  # world units — switch to braking phase
    ARRIVE_DIST =  40.0  # world units — count waypoint as reached

    def __init__(self, wx: float, wy: float, waypoints: list[tuple[float, float]],
                 team: int = 0):
        big = random.random() > 0.5
        if big:
            w = random.randint(88, 144)
            h = random.randint(40, 72)
        else:
            w = random.randint(48, 80)
            h = random.randint(24, 40)

        color = random.choice(_TEAM_COLORS[team])
        super().__init__(wx, wy, w, h, color)

        self.team        = team
        self.waypoints   = waypoints
        self.current_wp  = 0
        self.vx          = 0.0
        self.vy          = 0.0
        self.angle       = random.uniform(0, math.tau)
        self._thrusting  = False

        # Combat state
        self.max_hp          = 100 if big else 50
        self.hp              = self.max_hp
        self.alive           = True
        self.turret_angle    = random.uniform(0, math.tau)
        self._fire_cooldown  = random.uniform(0, FIRE_RATE)  # stagger first shots
        self._has_target     = False

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

    def update(self, dt: float):
        if not self.alive:
            return

        cx = self.wx + self.width  / 2
        cy = self.wy + self.height / 2
        tx, ty = self.target

        dx   = tx - cx
        dy   = ty - cy
        dist = math.hypot(dx, dy)

        self._thrusting = False

        if dist < self.ARRIVE_DIST:
            self.current_wp = (self.current_wp + 1) % len(self.waypoints)
        else:
            target_angle = math.atan2(dy, dx)
            speed        = math.hypot(self.vx, self.vy)

            if dist < self.DECEL_DIST and speed > 15.0:
                retro_angle = math.atan2(-self.vy, -self.vx)
                self._turn_toward(retro_angle, dt)
                if abs(self._angle_diff(retro_angle, self.angle)) < math.pi / 3:
                    self.vx += math.cos(self.angle) * self.THRUST * dt
                    self.vy += math.sin(self.angle) * self.THRUST * dt
                    self._thrusting = True
            else:
                self._turn_toward(target_angle, dt)
                aligned = abs(self._angle_diff(target_angle, self.angle)) < math.pi / 3
                if aligned and speed < self.MAX_SPEED:
                    self.vx += math.cos(self.angle) * self.THRUST * dt
                    self.vy += math.sin(self.angle) * self.THRUST * dt
                    self._thrusting = True

        drag = self.DRAG ** dt
        self.vx *= drag
        self.vy *= drag

        speed = math.hypot(self.vx, self.vy)
        if speed > self.MAX_SPEED:
            f = self.MAX_SPEED / speed
            self.vx *= f
            self.vy *= f

        self.wx += self.vx * dt
        self.wy += self.vy * dt

    def update_combat(self, dt: float, all_ships: list, bullets: list) -> None:
        """Rotate the turret toward the nearest enemy and fire when aligned."""
        if not self.alive:
            return

        cx = self.wx + self.width  / 2
        cy = self.wy + self.height / 2

        # Find nearest living enemy in range
        best_dist   = ATTACK_RANGE
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

        if best_target is not None:
            ex = best_target.wx + best_target.width  / 2
            ey = best_target.wy + best_target.height / 2
            desired = math.atan2(ey - cy, ex - cx)

            # Rotate turret toward target
            diff = self._angle_diff(desired, self.turret_angle)
            step = math.copysign(min(abs(diff), TURRET_TURN_RATE * dt), diff)
            raw  = self.turret_angle + step
            self.turret_angle = math.atan2(math.sin(raw), math.cos(raw))

            # Fire when aligned and cooldown ready
            self._fire_cooldown -= dt
            if self._fire_cooldown <= 0 and abs(diff) < 0.25:
                self._fire_cooldown = FIRE_RATE
                bullets.append(Bullet(cx, cy, self.turret_angle, self.team))
        else:
            self._fire_cooldown = max(0.0, self._fire_cooldown - dt)

    def take_damage(self, amount: int) -> None:
        self.hp -= amount
        if self.hp <= 0:
            self.hp    = 0
            self.alive = False

    def _turn_toward(self, target_angle: float, dt: float) -> None:
        diff = self._angle_diff(target_angle, self.angle)
        step = math.copysign(min(abs(diff), self.TURN_RATE * dt), diff)
        raw  = self.angle + step
        self.angle = math.atan2(math.sin(raw), math.cos(raw))

    @staticmethod
    def _angle_diff(target: float, current: float) -> float:
        """Shortest signed angle from current to target in [-π, π]."""
        return (target - current + math.pi) % (2 * math.pi) - math.pi

    def draw(self, surface: pygame.Surface, camera) -> None:
        if not self.alive or not camera.is_visible(self.world_rect):
            return

        cx, cy = camera.world_to_screen(
            self.wx + self.width  / 2,
            self.wy + self.height / 2,
        )

        cos_a = math.cos(self.angle)
        sin_a = math.sin(self.angle)
        L = self.width  / 2
        W = self.height / 2

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

        screen_pts = [to_screen(lx, ly) for lx, ly in local_pts]
        pygame.draw.polygon(surface, self.color, screen_pts)
        pygame.draw.polygon(surface, (255, 255, 255), screen_pts, 1)

        # Engine glow
        if self._thrusting:
            ex_s = -L * 0.85 * cos_a + cx
            ey_s = -L * 0.85 * sin_a + cy
            glow_r = max(2, int(W * 0.6))
            pygame.draw.circle(surface, (255, 180, 40), (int(ex_s), int(ey_s)), glow_r)

        # Turret base
        base_r = max(3, int(W * 0.35))
        turret_color = (200, 200, 200) if self._has_target else (130, 130, 130)
        pygame.draw.circle(surface, (60, 60, 60),   (int(cx), int(cy)), base_r + 1)
        pygame.draw.circle(surface, turret_color,   (int(cx), int(cy)), base_r)

        # Turret barrel
        barrel_len = max(int(L * 0.65), 10)
        barrel_w   = max(2, int(W * 0.18))
        tx_end = cx + math.cos(self.turret_angle) * barrel_len
        ty_end = cy + math.sin(self.turret_angle) * barrel_len
        pygame.draw.line(surface, turret_color,
                         (int(cx), int(cy)), (int(tx_end), int(ty_end)), barrel_w)

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
