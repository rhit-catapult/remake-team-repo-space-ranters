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


_SHIP_COLORS = [
    (255, 140,  60),   # orange
    (255,  80,  80),   # red
    ( 80, 200, 255),   # cyan
    (100, 255, 120),   # green
    (200, 100, 255),   # purple
    (255, 220,  60),   # gold
]


class AICharacter(Entity):
    """
    Spaceship AI flying between waypoints with vacuum-inertia physics.

    Movement phases:
      Cruise  — turn toward waypoint, thrust forward when aligned.
      Braking — turn to face retrograde (opposite velocity), thrust to slow down.

    Ships never snap direction: they rotate at TURN_RATE and drift between
    course corrections, giving the feel of spacecraft in a vacuum.
    """

    TURN_RATE   = 2.5    # radians / second
    THRUST      = 85.0   # world units / second²
    MAX_SPEED   = 120.0  # world units / second
    DRAG        = 0.97   # speed multiplier / second (light space drag)
    DECEL_DIST  = 250.0  # world units — switch to braking phase
    ARRIVE_DIST =  40.0  # world units — count waypoint as reached

    def __init__(self, wx: float, wy: float, waypoints: list[tuple[float, float]]):
        big = random.random() > 0.5
        if big:
            w = random.randint(88, 144)
            h = random.randint(40, 72)
        else:
            w = random.randint(48, 80)
            h = random.randint(24, 40)

        color = random.choice(_SHIP_COLORS)
        super().__init__(wx, wy, w, h, color)

        self.waypoints   = waypoints
        self.current_wp  = 0
        self.vx          = 0.0
        self.vy          = 0.0
        self.angle       = random.uniform(0, math.tau)
        self._thrusting  = False

    @property
    def target(self) -> tuple[float, float]:
        return self.waypoints[self.current_wp]

    # Use a square bounding box large enough to contain the ship at any rotation.
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
                # Braking: face retrograde and thrust to kill velocity.
                retro_angle = math.atan2(-self.vy, -self.vx)
                self._turn_toward(retro_angle, dt)
                if abs(self._angle_diff(retro_angle, self.angle)) < math.pi / 3:
                    self.vx += math.cos(self.angle) * self.THRUST * dt
                    self.vy += math.sin(self.angle) * self.THRUST * dt
                    self._thrusting = True
            else:
                # Cruise: turn toward waypoint and thrust when roughly aligned.
                self._turn_toward(target_angle, dt)
                aligned = abs(self._angle_diff(target_angle, self.angle)) < math.pi / 3
                if aligned and speed < self.MAX_SPEED:
                    self.vx += math.cos(self.angle) * self.THRUST * dt
                    self.vy += math.sin(self.angle) * self.THRUST * dt
                    self._thrusting = True

        # Light vacuum drag.
        drag = self.DRAG ** dt
        self.vx *= drag
        self.vy *= drag

        # Hard speed cap.
        speed = math.hypot(self.vx, self.vy)
        if speed > self.MAX_SPEED:
            f = self.MAX_SPEED / speed
            self.vx *= f
            self.vy *= f

        self.wx += self.vx * dt
        self.wy += self.vy * dt

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
        if not camera.is_visible(self.world_rect):
            return

        cx, cy = camera.world_to_screen(
            self.wx + self.width  / 2,
            self.wy + self.height / 2,
        )

        cos_a = math.cos(self.angle)
        sin_a = math.sin(self.angle)
        L = self.width  / 2   # half-length along facing axis
        W = self.height / 2   # half-width perpendicular

        # Elongated spaceship polygon: pointed nose, flared body.
        local_pts = [
            ( L,        0.0    ),   # nose tip
            ( L * 0.25, W      ),   # right shoulder
            (-L,        W * 0.6),   # right rear
            (-L,       -W * 0.6),   # left rear
            ( L * 0.25,-W      ),   # left shoulder
        ]

        def to_screen(lx, ly):
            return (lx * cos_a - ly * sin_a + cx,
                    lx * sin_a + ly * cos_a + cy)

        screen_pts = [to_screen(lx, ly) for lx, ly in local_pts]

        pygame.draw.polygon(surface, self.color, screen_pts)
        pygame.draw.polygon(surface, (255, 255, 255), screen_pts, 1)

        # Engine glow at rear when thrusting.
        if self._thrusting:
            ex_s = -L * 0.85 * cos_a + cx
            ey_s = -L * 0.85 * sin_a + cy
            glow_r = max(2, int(W * 0.6))
            pygame.draw.circle(surface, (255, 180, 40), (int(ex_s), int(ey_s)), glow_r)
