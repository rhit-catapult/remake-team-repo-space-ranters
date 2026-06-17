"""
CommandCenter — Defensive structure mounted on the Constructor.
Destroying the opponent's command center is the primary win condition.
"""
import math
import pygame


class CommandCenter:
    """A defensive command structure mounted on top of the Constructor.

    Represents the heart of each team's operation. Destroying the enemy's
    command center is the only way to win. The command center:
    - Stays mounted on the Constructor (moves with it as the planet orbits)
    - Has health and can be damaged
    - Can be targeted and attacked like other entities
    - Creates an explosion when destroyed
    """

    # Team colors for rendering
    _COLORS = [(100, 150, 255), (255, 100, 100)]  # Blue, Red

    # Health configuration
    MAX_HP = 350

    def __init__(self, constructor, team: int):
        """
        Args:
            constructor: Constructor object to stay mounted on
            team: 0 for Blue, 1 for Red
        """
        self.constructor = constructor
        self.team = team

        # Health & state
        self.max_hp = self.MAX_HP
        self.hp = self.max_hp
        self.alive = True

        # Dimensions — matches the Constructor footprint
        self.radius = 70
        self.width = self.radius * 2
        self.height = self.radius * 2

        # Animation timer
        self.time = 0.0

        # Color
        self.color = self._COLORS[team]
        self._col_dark = tuple(max(0, c - 90) for c in self.color)
        self._col_bright = tuple(min(255, c + 60) for c in self.color)

        # Position (updated in update())
        self.wx = 0.0
        self.wy = 0.0
        self._update_position()

    def _update_position(self):
        """Snap position to the Constructor's current center."""
        self.wx = self.constructor.wx + self.constructor.radius - self.radius
        self.wy = self.constructor.wy + self.constructor.radius - self.radius

    @property
    def world_rect(self) -> pygame.Rect:
        """Return world-space bounding rect."""
        return pygame.Rect(int(self.wx), int(self.wy), self.width, self.height)

    def update(self, dt: float):
        """Advance animation timer and stay mounted on the Constructor."""
        if not self.alive:
            return
        self.time += dt
        self._update_position()

    def take_damage(self, damage: float):
        """Reduce health by damage amount. Kills if hp <= 0."""
        if not self.alive:
            return
        self.hp -= damage
        if self.hp <= 0:
            self.hp = 0
            self.alive = False

    def try_take_damage(self, damage: float) -> bool:
        """Take damage with a hit chance roll. Returns True if hit."""
        import random
        if random.random() < 0.95:
            self.take_damage(damage)
            return True
        return False

    def draw(self, surface: pygame.Surface, camera):
        """Render the command center as an animated orbital defense station."""
        if not self.alive or not camera.is_visible_xywh(self.wx, self.wy,
                                                         self.width, self.height):
            return

        cx, cy = camera.world_to_screen(self.wx + self.radius, self.wy + self.radius)
        r = max(1, int(self.radius * camera.zoom))
        zoom = camera.zoom
        lw = max(1, int(zoom))

        # ── Pulsing glow halo ─────────────────────────────────────────────────
        pulse = 0.5 + 0.5 * math.sin(self.time * 1.8)
        for step in range(3, 0, -1):
            frac = step / 3
            glow_r = int(r * (1.25 + step * 0.18))
            gc = tuple(min(255, int(55 + c * frac * pulse * 0.35)) for c in self.color)
            if glow_r > 1:
                pygame.draw.circle(surface, gc, (cx, cy), glow_r)

        # ── Outer octagon hull — slow time-based spin ─────────────────────────
        n_sides = 8
        spin = self.time * 0.35
        pts = []
        for i in range(n_sides):
            a = spin + i * math.tau / n_sides
            px = cx + math.cos(a) * r
            py = cy + math.sin(a) * r
            pts.append((int(px), int(py)))
        pygame.draw.polygon(surface, self._col_dark, pts)
        pygame.draw.polygon(surface, self.color, pts, max(1, int(2 * zoom)))

        # ── Six defense pods counter-rotating around the hull ─────────────────
        pod_r = int(r * 0.78)
        pod_size = max(2, int(r * 0.12))
        pod_spin = self.time * -0.55
        for i in range(6):
            a = pod_spin + i * math.tau / 6
            px = int(cx + math.cos(a) * pod_r)
            py = int(cy + math.sin(a) * pod_r)
            pod_pulse = 0.5 + 0.5 * math.sin(self.time * 3.0 + i * 1.05)
            pc = tuple(min(255, int(c * pod_pulse)) for c in self._col_bright)
            pygame.draw.circle(surface, self._col_dark, (px, py), pod_size)
            pygame.draw.circle(surface, pc, (px, py), max(1, pod_size - 1))

        # ── Inner rotating radar arcs (3 partial arcs, time-driven) ──────────
        inner_r = int(r * 0.52)
        arc_spin = self.time * 1.3
        frac_arc = 0.38
        n_seg = max(5, int(12 * frac_arc))
        for i in range(3):
            a_start = arc_spin + i * math.tau / 3
            a_end = a_start + math.tau * frac_arc
            seg_c = tuple(min(255, int(c * (0.55 + 0.2 * i))) for c in self._col_bright)
            prev_p = None
            for k in range(n_seg + 1):
                a = a_start + (a_end - a_start) * k / n_seg
                pt = (int(cx + math.cos(a) * inner_r),
                      int(cy + math.sin(a) * inner_r))
                if prev_p and inner_r >= 2:
                    pygame.draw.line(surface, seg_c, prev_p, pt, lw)
                prev_p = pt

        # ── Central command core with pulsing ─────────────────────────────────
        core_r = max(2, int(r * 0.28))
        cp = 0.55 + 0.45 * math.sin(self.time * 4.2)
        core_c = tuple(min(255, int(c * cp)) for c in self._col_bright)
        pygame.draw.circle(surface, self._col_dark, (cx, cy), core_r)
        pygame.draw.circle(surface, core_c, (cx, cy), max(1, core_r - 1))

        # ── Damage warning flash ──────────────────────────────────────────────
        if self.hp < self.max_hp * 0.5 and math.sin(self.time * 6.0) > 0:
            pygame.draw.circle(surface, (255, 60, 60),
                               (cx + int(r * 0.28), cy - int(r * 0.28)),
                               max(2, int(r * 0.08)))

        # ── Health bar when damaged ───────────────────────────────────────────
        if self.hp < self.max_hp:
            bar_w = r * 2
            bar_h = max(2, int(3 * zoom))
            bar_x = cx - bar_w // 2
            bar_y = cy - r - 12
            pygame.draw.rect(surface, (120, 0, 0), (bar_x, bar_y, bar_w, bar_h))
            fill_w = int(bar_w * self.hp / self.max_hp)
            pygame.draw.rect(surface, (0, 210, 60), (bar_x, bar_y, fill_w, bar_h))
            pygame.draw.rect(surface, (200, 200, 200), (bar_x, bar_y, bar_w, bar_h), 1)
