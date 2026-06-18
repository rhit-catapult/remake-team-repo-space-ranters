"""
entity.py — Game objects that exist in world space.
All positions are world coordinates; the camera handles rendering.
"""
import math
import random
import pygame

_ALL_MATERIALS = [
    'iron', 'nickel', 'copper', 'silicon', 'ice',
    'helium3', 'fuel', 'titanium', 'platinum', 'crystal', 'uranium',
]


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


class Star(Entity):
    """A team-coloured star at the centre of a solar system."""

    def __init__(self, cx: float, cy: float, radius: int, color):
        super().__init__(cx - radius, cy - radius, radius * 2, radius * 2, color)
        self.cx = cx
        self.cy = cy
        self.radius = radius
        self._glow_color = tuple(min(255, c + 80) for c in color)

    def update(self, dt: float):
        pass

    def draw(self, surface: pygame.Surface, camera) -> None:
        if not camera.is_visible_xywh(self.wx, self.wy, self.width, self.height):
            return
        sx, sy = camera.world_to_screen(self.cx, self.cy)
        r = max(1, int(self.radius * camera.zoom))
        pygame.draw.circle(surface, self._glow_color, (sx, sy), r + 4)
        pygame.draw.circle(surface, self.color, (sx, sy), r)


class Planet(Entity):
    """A planet orbiting a star."""

    _PLANET_COLORS = {
        'rocky': (170, 145, 115),
        'water': (90, 150, 240),
        'gas':   (220, 180, 100),
    }
    _HOME_COLORS = [(120, 190, 255), (255, 150, 150)]

    def __init__(self, star_x: float, star_y: float, orbit_radius: float,
                 angle: float, orbit_speed: float, planet_type: str,
                 team: int, radius: int):
        self.star_x = star_x
        self.star_y = star_y
        self.orbit_radius = orbit_radius
        self.angle = angle
        self.orbit_speed = orbit_speed
        self.planet_type = planet_type
        self.team = team
        self.radius = radius
        color = self._HOME_COLORS[team] if planet_type == 'home' else self._PLANET_COLORS[planet_type]
        super().__init__(star_x + math.cos(angle) * orbit_radius - radius,
                         star_y + math.sin(angle) * orbit_radius - radius,
                         radius * 2, radius * 2, color)
        # Set yields based on planet type (from MinerShip._PLANET_YIELDS)
        yields_map = {
            'home':  {'iron': 2.0, 'nickel': 1.5},
            'rocky': {'iron': 5.0, 'nickel': 3.0, 'copper': 2.0},
            'water': {'ice': 3.0, 'silicon': 2.5},
            'gas':   {'helium3': 2.0, 'fuel': 3.5},
        }
        self.yields = yields_map.get(planet_type, {})

    def update(self, dt: float):
        self.angle = (self.angle + self.orbit_speed * dt) % math.tau
        self.wx = self.star_x + math.cos(self.angle) * self.orbit_radius - self.radius
        self.wy = self.star_y + math.sin(self.angle) * self.orbit_radius - self.radius

    def draw(self, surface: pygame.Surface, camera, show_orbit: bool = True) -> None:
        if show_orbit:
            sx, sy = camera.world_to_screen(self.star_x, self.star_y)
            orbit_r = int(self.orbit_radius * camera.zoom)
            if orbit_r > 2:
                pygame.draw.circle(surface, (80, 80, 90), (sx, sy), orbit_r, 1)

        if not camera.is_visible_xywh(self.wx, self.wy, self.width, self.height):
            return

        cx, cy = camera.world_to_screen(self.wx + self.radius, self.wy + self.radius)
        r = max(1, int(self.radius * camera.zoom))
        pygame.draw.circle(surface, self.color, (cx, cy), r)
        if self.planet_type == 'gas':
            pygame.draw.circle(surface, (255, 255, 255), (cx, cy), r, 1)


class Constructor(Entity):
    """Ship constructor stationed on the home planet. Also the win-condition target."""

    _COLORS     = [(180, 220, 255), (255, 180, 180)]
    _BUILD_TIME = 12.0   # seconds to complete one queued ship
    MAX_HP      = 500

    def __init__(self, home_planet: Planet, team: int):
        self.home_planet = home_planet
        self.team = team
        self.build_timer = self._BUILD_TIME   # counts down once a job is queued
        self.build_queue: list = []           # ship-type strings waiting to be built
        self.time = 0.0
        radius = 65
        color = self._COLORS[team]
        planet_cx = home_planet.wx + home_planet.radius
        planet_cy = home_planet.wy + home_planet.radius
        super().__init__(planet_cx - radius, planet_cy - radius,
                         radius * 2, radius * 2, color)
        self.radius = radius
        self.face_angle = -math.pi * 0.5
        self._col_dark   = tuple(max(0, c - 90) for c in color)
        self._col_mid    = tuple(max(0, c - 45) for c in color)
        self._col_bright = tuple(min(255, c + 60) for c in color)
        self.max_hp = self.MAX_HP
        self.hp     = self.max_hp
        self.alive  = True

    def take_damage(self, amount: float) -> None:
        if not self.alive:
            return
        self.hp -= amount
        if self.hp <= 0:
            self.hp = 0
            self.alive = False

    def try_take_damage(self, amount: float) -> bool:
        if random.random() < 0.95:
            self.take_damage(amount)
            return True
        return False

    def queue_build(self, ship_type: str) -> None:
        """Add a ship type to the build queue."""
        self.build_queue.append(ship_type)

    def _build_progress(self) -> float:
        """0 = idle/just started, 1 = about to complete."""
        if not self.build_queue:
            return 0.0
        return max(0.0, min(1.0, 1.0 - self.build_timer / self._BUILD_TIME))

    def update(self, dt: float):
        if not self.alive:
            return None
        planet_cx = self.home_planet.wx + self.home_planet.radius
        planet_cy = self.home_planet.wy + self.home_planet.radius
        self.wx = planet_cx - self.radius
        self.wy = planet_cy - self.radius
        self.time += dt

        if self.build_queue:
            self.build_timer -= dt
            if self.build_timer <= 0.0:
                self.build_timer = self._BUILD_TIME
                build_type = self.build_queue.pop(0)
                return (build_type,
                        self.wx + self.radius,
                        self.wy + self.radius,
                        self.team)
        else:
            self.build_timer = self._BUILD_TIME   # reset so next job starts promptly
        return None

    def draw(self, surface: pygame.Surface, camera) -> None:
        if not self.alive or not camera.is_visible_xywh(self.wx, self.wy, self.width, self.height):
            return
        cx, cy = camera.world_to_screen(self.wx + self.radius, self.wy + self.radius)
        zoom     = camera.zoom
        R        = max(6, int(self.radius * 1.8 * zoom))
        progress = self._build_progress()
        building = bool(self.build_queue)

        col    = self.color
        dark   = self._col_dark
        mid    = self._col_mid
        bright = self._col_bright
        lw     = max(1, int(zoom * 1.5))

        def r(f): return int(f * R)

        # ── Outer hexagonal perimeter ──────────────────────────────────────────
        hex_r    = r(1.25)
        hex_pts  = [(cx + int(math.cos(k * math.tau / 6) * hex_r),
                     cy + int(math.sin(k * math.tau / 6) * hex_r))
                    for k in range(6)]
        pygame.draw.polygon(surface, dark, hex_pts)
        pygame.draw.polygon(surface, mid,  hex_pts, max(2, lw))

        # Inner chamfer ring
        hex2_r   = hex_r - max(2, r(0.06))
        hex2_pts = [(cx + int(math.cos(k * math.tau / 6) * hex2_r),
                     cy + int(math.sin(k * math.tau / 6) * hex2_r))
                    for k in range(6)]
        pygame.draw.polygon(surface, bright, hex2_pts, lw)

        # ── Six processing nodes at hex vertices ───────────────────────────────
        node_d = r(0.75)
        nodes  = [(cx + int(math.cos(k * math.tau / 6) * node_d),
                   cy + int(math.sin(k * math.tau / 6) * node_d))
                  for k in range(6)]
        nr = max(3, r(0.12))

        # Spoke conduits center → each node
        for nx, ny in nodes:
            pygame.draw.line(surface, mid, (cx, cy), (nx, ny), lw)

        # Energy ring connecting adjacent nodes (pulses when active)
        pulse = 0.45 + 0.55 * abs(math.sin(self.time * 2.5)) if building else 0.40
        ec    = tuple(min(255, int(c * pulse)) for c in bright)
        for i in range(6):
            pygame.draw.line(surface, ec, nodes[i], nodes[(i + 1) % 6], max(1, lw))

        # Node bodies
        for i, (nx, ny) in enumerate(nodes):
            pygame.draw.circle(surface, dark, (nx, ny), nr)
            pygame.draw.circle(surface, col if i % 2 == 0 else mid, (nx, ny), nr, lw)
            if building:
                cp = 0.4 + 0.6 * abs(math.sin(self.time * 3.0 + i * math.pi / 3))
                nc = tuple(min(255, int(c * cp)) for c in bright)
                pygame.draw.circle(surface, nc, (nx, ny), max(1, nr // 2))
            else:
                pygame.draw.circle(surface, mid, (nx, ny), max(1, nr // 2))

        # ── Assembly platforms between alternating node pairs ──────────────────
        for i in range(3):
            a_bay         = (2 * i + 1) * math.tau / 6
            bx            = cx + int(math.cos(a_bay) * r(0.90))
            by            = cy + int(math.sin(a_bay) * r(0.90))
            hd            = max(1, r(0.07))   # radial half-depth
            hw2           = max(2, r(0.13))   # tangential half-width
            cos_b, sin_b  = math.cos(a_bay), math.sin(a_bay)
            corners       = [
                (bx + int(cos_b * dd - sin_b * tt),
                 by + int(sin_b * dd + cos_b * tt))
                for dd, tt in [(-hd, -hw2), (hd, -hw2), (hd, hw2), (-hd, hw2)]
            ]
            pygame.draw.polygon(surface, tuple(max(0, c - 30) for c in dark), corners)
            pygame.draw.polygon(surface, mid, corners, lw)

        # ── Central reactor ─────────────────────────────────────────────────────
        reactor_r = r(0.36)
        pygame.draw.circle(surface, dark, (cx, cy), reactor_r)
        pygame.draw.circle(surface, col,  (cx, cy), reactor_r, max(2, int(lw * 1.5)))

        # Three rotating partial-arc rings inside the reactor
        for ring_i in range(3):
            rr     = max(2, int(reactor_r * (0.76 - ring_i * 0.24)))
            spd    = (0.5 + ring_i * 0.5) * (1.8 if building else 0.5)
            a_rot  = self.time * spd
            frac   = 0.68
            n_pts  = max(6, int(18 * frac))
            seg_c  = tuple(min(255, int(c * (0.45 + 0.30 * ring_i))) for c in bright)
            prev_p = None
            for k in range(n_pts + 1):
                a  = a_rot + k * math.tau * frac / n_pts
                pt = (cx + int(math.cos(a) * rr), cy + int(math.sin(a) * rr))
                if prev_p and rr >= 2:
                    pygame.draw.line(surface, seg_c, prev_p, pt, lw)
                prev_p = pt

        # Reactor core
        core_r = max(2, r(0.09))
        if building:
            cp2    = 0.6 + 0.4 * math.sin(self.time * 6.0)
            core_c = tuple(min(255, int(c * cp2)) for c in bright)
        else:
            core_c = mid
        pygame.draw.circle(surface, core_c, (cx, cy), core_r)

        # ── Construction activity ──────────────────────────────────────────────
        if building:
            a0 = self.time * 2.0
            for k in range(4):
                ka = a0 + k * math.tau / 4
                kx = cx + int(math.cos(ka) * r(0.54))
                ky = cy + int(math.sin(ka) * r(0.54))
                kc = tuple(min(255, int(c * abs(math.sin(a0 + k * 0.8)))) for c in bright)
                pygame.draw.circle(surface, kc, (kx, ky), max(2, r(0.05)))

        # ── Damage warning ─────────────────────────────────────────────────────
        if self.hp < self.max_hp * 0.5 and math.sin(self.time * 6.0) > 0:
            pygame.draw.circle(surface, (255, 60, 60),
                               (cx + r(0.28), cy - r(0.28)), max(2, r(0.07)))

        # ── Health bar ─────────────────────────────────────────────────────────
        bar_w  = r(2.5)
        bar_h  = max(2, int(3 * zoom))
        bar_x  = cx - bar_w // 2
        bar_y  = cy - hex_r - bar_h - max(2, r(0.06))
        pygame.draw.rect(surface, (120, 0, 0),    (bar_x, bar_y, bar_w, bar_h))
        fill_w = int(bar_w * self.hp / self.max_hp)
        pygame.draw.rect(surface, (0, 210, 60),   (bar_x, bar_y, fill_w, bar_h))
        pygame.draw.rect(surface, (200, 200, 200), (bar_x, bar_y, bar_w, bar_h), 1)

        # ── Build progress arc ─────────────────────────────────────────────────
        if progress > 0.0:
            arc_r   = hex_r + max(3, r(0.06))
            arc_lw  = max(2, int(3 * zoom))
            a_start = -math.pi / 2
            a_end   = a_start + math.tau * progress
            arc_col = (int(80 + 175 * progress), int(220 - 60 * progress), 40)
            n_seg   = max(4, int(36 * progress))
            prev_pt = None
            for seg in range(n_seg + 1):
                a   = a_start + (a_end - a_start) * seg / n_seg
                pt  = (int(cx + math.cos(a) * arc_r),
                       int(cy + math.sin(a) * arc_r))
                if prev_pt:
                    pygame.draw.line(surface, arc_col, prev_pt, pt, arc_lw)
                prev_pt = pt



class DysonSphere(Entity):
    """Megastructure energy-collector ring encircling the team star."""

    _RING_COLORS = [(60, 140, 255), (255, 60, 60)]

    def __init__(self, star_x: float, star_y: float, star_radius: int, team: int):
        self.star_x = star_x
        self.star_y = star_y
        self.star_radius = star_radius
        self.team = team
        self.orbit_radius = star_radius + 350
        self.rotation = 0.0
        self.time = 0.0
        color = self._RING_COLORS[team]
        r = self.orbit_radius
        super().__init__(star_x - r, star_y - r, r * 2, r * 2, color)
        self._col_bright = tuple(min(255, c + 80) for c in color)
        self._col_dim    = tuple(max(0, c - 60)  for c in color)
        # Precomputed spoke step (radians)
        self._spoke_step = math.tau / 16
        self._panel_step = math.tau / 8
        self._node_step  = math.tau / 6

    def update(self, dt: float):
        self.rotation = (self.rotation + 0.012 * dt) % math.tau
        self.time += dt

    def draw(self, surface: pygame.Surface, camera) -> None:
        if not camera.is_visible_xywh(self.wx, self.wy, self.width, self.height):
            return
        sx, sy = camera.world_to_screen(self.star_x, self.star_y)
        r = int(self.orbit_radius * camera.zoom)
        if r < 4:
            return
        zoom = camera.zoom
        col    = self.color
        bright = self._col_bright
        dim    = self._col_dim

        # Energy corona glow — concentric rings, no Surface allocation
        pulse  = 0.6 + 0.4 * math.sin(self.time * 1.2)
        glow_r = r + max(2, int(10 * zoom))
        thick  = max(1, int(6 * zoom))
        for step in range(3, 0, -1):
            frac = step / 3
            gc = (int(col[0] * frac * 0.45 * pulse),
                  int(col[1] * frac * 0.45 * pulse),
                  int(col[2] * frac * 0.45 * pulse))
            pygame.draw.circle(surface, gc, (sx, sy),
                               glow_r + thick * (3 - step), thick)

        # Outer structural ring
        pygame.draw.circle(surface, col, (sx, sy), r, max(1, int(3 * zoom)))

        # Inner support ring
        inner_r = int(r * 0.72)
        pygame.draw.circle(surface, dim, (sx, sy), inner_r, max(1, int(zoom)))

        # Radial spokes
        step = self._spoke_step
        lw   = max(1, int(zoom))
        for i in range(16):
            angle = self.rotation + i * step
            cos_a = math.cos(angle)
            sin_a = math.sin(angle)
            pygame.draw.line(surface, dim,
                             (int(sx + cos_a * r),      int(sy + sin_a * r)),
                             (int(sx + cos_a * inner_r), int(sy + sin_a * inner_r)),
                             lw)

        # Panel chord bracing
        step8 = self._panel_step
        for i in range(8):
            a1 = self.rotation + i * step8
            a2 = a1 + step8
            pygame.draw.line(surface, dim,
                             (int(sx + math.cos(a1) * r), int(sy + math.sin(a1) * r)),
                             (int(sx + math.cos(a2) * r), int(sy + math.sin(a2) * r)),
                             lw)

        # Energy-collector nodes — no Surface allocation
        node_rot  = self.rotation * 0.6
        step6     = self._node_step
        node_r    = max(2, int(5 * zoom))
        node_r2   = node_r * 2
        for i in range(6):
            angle      = node_rot + i * step6
            nx         = int(sx + math.cos(angle) * r)
            ny         = int(sy + math.sin(angle) * r)
            node_pulse = 0.5 + 0.5 * math.sin(self.time * 2.5 + i * 1.0)
            gc = (int(bright[0] * node_pulse * 0.6),
                  int(bright[1] * node_pulse * 0.6),
                  int(bright[2] * node_pulse * 0.6))
            pygame.draw.circle(surface, gc, (nx, ny), node_r2)
            pygame.draw.circle(surface, bright, (nx, ny), node_r)


class DysonNode(Entity):
    """Command/relay station orbiting the Dyson sphere."""

    _COLORS = [(80, 160, 255), (255, 80, 80)]

    def __init__(self, star_x: float, star_y: float, orbit_radius: float,
                 angle: float, orbit_speed: float, team: int, node_index: int):
        self.star_x = star_x
        self.star_y = star_y
        self.orbit_radius = orbit_radius
        self.angle = angle
        self.orbit_speed = orbit_speed
        self.team = team
        self.node_index = node_index
        self.time = 0.0
        self.radius = 28
        color = self._COLORS[team]
        super().__init__(star_x + math.cos(angle) * orbit_radius - self.radius,
                         star_y + math.sin(angle) * orbit_radius - self.radius,
                         self.radius * 2, self.radius * 2, color)
        self._col_bright   = tuple(min(255, c + 80) for c in color)
        self._col_dark     = tuple(max(0, c - 80)   for c in color)
        self._col_emit     = tuple(min(255, int(c * 0.4 + 150)) for c in color)

    def update(self, dt: float):
        self.angle = (self.angle + self.orbit_speed * dt) % math.tau
        self.wx = self.star_x + math.cos(self.angle) * self.orbit_radius - self.radius
        self.wy = self.star_y + math.sin(self.angle) * self.orbit_radius - self.radius
        self.time += dt

    @staticmethod
    def _poly_points(cx, cy, r, sides, rotation=0.0):
        return [
            (cx + math.cos(rotation + i * math.tau / sides) * r,
             cy + math.sin(rotation + i * math.tau / sides) * r)
            for i in range(sides)
        ]

    def draw(self, surface: pygame.Surface, camera) -> None:
        if not camera.is_visible_xywh(self.wx, self.wy, self.width, self.height):
            return
        cx, cy = camera.world_to_screen(
            self.wx + self.radius, self.wy + self.radius)
        r = max(2, int(self.radius * camera.zoom))
        zoom = camera.zoom
        col    = self.color
        bright = self._col_bright
        dark   = self._col_dark

        # Pulsing glow halo — concentric circles, no Surface allocation
        pulse  = 0.5 + 0.5 * math.sin(self.time * 2.0 + self.node_index * 0.9)
        glow_r = int(r * 1.8)
        for step in range(3, 0, -1):
            frac = step / 3
            gc = (int(col[0] * frac * pulse * 0.5),
                  int(col[1] * frac * pulse * 0.5),
                  int(col[2] * frac * pulse * 0.5))
            pygame.draw.circle(surface, gc, (cx, cy), int(glow_r * frac))

        # Hexagonal hull, slowly counter-rotating
        hull_pts = self._poly_points(cx, cy, r, 6, self.time * 0.2)
        pygame.draw.polygon(surface, col, hull_pts)
        pygame.draw.polygon(surface, bright, hull_pts, max(1, int(zoom)))
        lw = max(1, int(zoom))
        for i in range(0, 6, 2):
            pygame.draw.line(surface, dark,
                             (int(hull_pts[i][0]), int(hull_pts[i][1])),
                             (int(hull_pts[(i + 3) % 6][0]), int(hull_pts[(i + 3) % 6][1])),
                             lw)

        # Solar panel wings
        wing_angle = self.time * 0.15 + self.node_index * (math.pi / 3)
        wing_len = int(r * 1.5)
        wing_w = max(2, int(r * 0.35))
        half_pi = math.pi / 2
        for side in (-1, 1):
            wa = wing_angle + side * half_pi
            tip_x = int(cx + math.cos(wa) * wing_len)
            tip_y = int(cy + math.sin(wa) * wing_len)
            pygame.draw.line(surface, dark, (cx, cy), (tip_x, tip_y), wing_w + 1)
            pygame.draw.line(surface, col,  (cx, cy), (tip_x, tip_y), max(1, wing_w - 1))

        # Central energy emitter
        pygame.draw.circle(surface, self._col_emit, (cx, cy), max(1, int(r * 0.35)))

        # Blinking antenna
        ant_a = wing_angle - half_pi
        ant_x = int(cx + math.cos(ant_a) * r * 1.15)
        ant_y = int(cy + math.sin(ant_a) * r * 1.15)
        if pulse > 0.65:
            pygame.draw.circle(surface, (255, 255, 100), (ant_x, ant_y),
                               max(1, int(2 * zoom)))


class MinerShip(Entity):
    """
    Flies to a team planet and lands permanently.  Mines indefinitely;
    CargoShips drain its cargo buffer and ferry resources to the Constructor.
    """

    SPEED      = 310.0
    DOCK_RANGE = 300.0

    # Infinite-resource planet yields  {ptype: {material: rate/s}}
    _PLANET_YIELDS = {
        'home':  {'iron': 2.0, 'nickel': 1.5},
        'rocky': {'iron': 5.0, 'nickel': 3.0, 'copper': 2.0},
        'water': {'ice': 3.0, 'silicon': 2.5},
        'gas':   {'helium3': 2.0, 'fuel': 3.5},
    }
    # Finite asteroid yields  {ptype: {material: rate/s}}  — rates sum to total depletion rate
    _ASTEROID_YIELDS = {
        'asteroid': {'titanium': 8.0, 'uranium': 4.0},
        'glowing':  {'crystal': 5.0, 'platinum': 3.0},
    }

    def __init__(self, wx: float, wy: float, team: int, planets: list):
        color = (200, 235, 255) if team == 0 else (255, 210, 200)
        super().__init__(wx, wy, 28, 15, color)
        self.team           = team
        self.alive          = True
        self.planets        = planets
        self.cargo_hold = {
            'iron': 0.0, 'nickel': 0.0, 'copper': 0.0, 'silicon': 0.0, 'ice': 0.0,
            'helium3': 0.0, 'fuel': 0.0, 'titanium': 0.0, 'platinum': 0.0,
            'crystal': 0.0, 'uranium': 0.0,
        }
        self.state          = 'idle'
        self._target        = None
        self._landed_planet = None
        self.vx = self.vy   = 0.0
        self.angle          = 0.0
        self.time           = 0.0
        self._land_offset   = 0.0   # surface angle offset relative to planet.angle at landing
        self._drill_spin    = 0.0   # animated drill rotation counter
        self.max_hp         = 60
        self.hp             = 60
        self.drill_hp       = 100.0
        self.drill_max_hp   = 100.0
        self._needs_defense = False  # set True by active escort orders; cleared each frame
        self._asteroid_mode = False  # True while assigned to an asteroid; auto-reassigns on depletion
        self.asteroids      = []     # shared list reference; set from main.py after construction
        self._sep_ax        = 0.0
        self._sep_ay        = 0.0

    def send_to(self, planet) -> None:
        """Order this miner to fly to and land on planet/asteroid."""
        self._target        = planet
        self.state          = 'to_planet'
        ptype               = getattr(planet, 'planet_type', None)
        self._asteroid_mode = ptype in ('asteroid', 'glowing')

    def update(self, dt: float) -> None:
        if not self.alive:
            return
        self.time += dt

        if self.state not in ('idle', 'landed'):
            _sm = math.hypot(self._sep_ax, self._sep_ay)
            if _sm > 200.0:
                self._sep_ax *= 200.0 / _sm
                self._sep_ay *= 200.0 / _sm
            self.wx += self._sep_ax * dt
            self.wy += self._sep_ay * dt
        self._sep_ax = 0.0
        self._sep_ay = 0.0

        if self.state == 'idle':
            return

        if self.state == 'landed':
            if self._landed_planet is not None:
                pcx          = self._landed_planet.wx + self._landed_planet.radius
                pcy          = self._landed_planet.wy + self._landed_planet.radius
                planet_angle = getattr(self._landed_planet, 'angle', 0.0)
                abs_angle    = planet_angle + self._land_offset
                pr           = self._landed_planet.radius
                self.wx    = pcx + math.cos(abs_angle) * pr - self.width  / 2
                self.wy    = pcy + math.sin(abs_angle) * pr - self.height / 2
                self.angle = abs_angle + math.pi   # nose faces inward toward planet
                if self.drill_hp > 0:
                    self._drill_spin += 4.5 * dt
                    ptype = getattr(self._landed_planet, 'planet_type', None)
                    if hasattr(self._landed_planet, 'resources'):
                        # Finite asteroid: split total mined proportionally across yields
                        yields     = getattr(self._landed_planet, 'yields',
                                             self._ASTEROID_YIELDS.get(ptype, {}))
                        total_rate = sum(yields.values()) or 1.0
                        mined      = min(total_rate * dt, self._landed_planet.resources)
                        self._landed_planet.resources -= mined
                        if self._landed_planet.resources <= 0:
                            self._landed_planet.alive = False
                            depleted                  = self._landed_planet
                            self._landed_planet       = None
                            if self._asteroid_mode and self.asteroids:
                                next_a = next(
                                    (a for a in self.asteroids
                                     if a is not depleted and a.alive
                                     and getattr(a, 'resources', 1) > 0),
                                    None,
                                )
                                if next_a is not None:
                                    self.send_to(next_a)
                                    return
                            self.state = 'idle'
                            return
                        for mat, rate in yields.items():
                            self.cargo_hold[mat] += mined * (rate / total_rate)
                    else:
                        # Infinite planet: add all yields for this planet type
                        for mat, rate in getattr(self._landed_planet, 'yields',
                                                 self._PLANET_YIELDS.get(ptype, {})).items():
                            self.cargo_hold[mat] += rate * dt
            return

        if self.state == 'to_planet':
            if self._target is None:
                self._select_planet()
                return
            tx = self._target.wx + self._target.radius
            ty = self._target.wy + self._target.radius
            self._move_toward(tx, ty, dt)
            if math.hypot(tx - (self.wx + self.width  / 2),
                          ty - (self.wy + self.height / 2)) < self.DOCK_RANGE:
                self.state          = 'landed'
                self._landed_planet = self._target
                mcx = self.wx + self.width  / 2
                mcy = self.wy + self.height / 2
                abs_surface       = math.atan2(mcy - ty, mcx - tx)
                self._land_offset = abs_surface - getattr(self._target, 'angle', 0.0)

    def _move_toward(self, tx: float, ty: float, dt: float) -> None:
        cx   = self.wx + self.width  / 2
        cy   = self.wy + self.height / 2
        dx   = tx - cx
        dy   = ty - cy
        dist = math.hypot(dx, dy)
        if dist > 2.0:
            self.angle = math.atan2(dy, dx)
            spd = self.SPEED if dist > 350 else self.SPEED * (dist / 350)
            self.vx = math.cos(self.angle) * spd
            self.vy = math.sin(self.angle) * spd
        else:
            self.vx = self.vy = 0.0
        self.wx += self.vx * dt
        self.wy += self.vy * dt

    @property
    def hit_chance(self) -> float:
        return 0.60

    def take_damage(self, amount: int) -> None:
        self.hp -= amount
        if self.state == 'landed':
            self.drill_hp = max(0.0, self.drill_hp - amount * 1.5)
        if self.hp <= 0:
            self.hp    = 0
            self.alive = False

    def try_take_damage(self, amount: int) -> bool:
        if random.random() < self.hit_chance:
            self.take_damage(amount)
            return True
        return False

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

        def ts(lx, ly):
            return (int(cx + lx * cos_a - ly * sin_a),
                    int(cy + lx * sin_a + ly * cos_a))

        # Pulsing landing-ring when settled on a planet
        if self.state == 'landed':
            pulse    = 0.5 + 0.5 * math.sin(self.time * 2.5)
            r_ring   = max(6, int((L + W) * 0.75))
            ring_col = (int(60 * pulse), int(200 * pulse), int(90 * pulse))
            pygame.draw.circle(surface, ring_col, (cx, cy), r_ring + 2, 1)

        # Boxy utility hull
        pts = [ts(L, 0), ts(L * 0.3, W), ts(-L, W * 0.7), ts(-L, -W * 0.7), ts(L * 0.3, -W)]
        pygame.draw.polygon(surface, self.color, pts)
        rim = (200, 255, 200) if self.state == 'landed' else (255, 255, 255)
        pygame.draw.polygon(surface, rim, pts, 1)

        # ── Animated drill when landed ────────────────────────────────────
        if self.state == 'landed':
            drill_frac = self.drill_hp / self.drill_max_hp
            broken     = self.drill_hp <= 0
            shaft_ext  = L * 1.1
            shaft_s    = ts(L, 0)
            shaft_e    = ts(L + shaft_ext, 0)
            shaft_col  = (160, 40, 30) if broken else (int(140 * drill_frac + 60 * (1 - drill_frac)),
                                                        int(135 * drill_frac + 30 * (1 - drill_frac)),
                                                        int(115 * drill_frac + 20 * (1 - drill_frac)))
            pygame.draw.line(surface, shaft_col, shaft_s, shaft_e,
                             max(2, int(3 * camera.zoom)))
            if not broken:
                # Helical stripes scrolling along the shaft
                for i in range(5):
                    t = ((i / 5) + self._drill_spin * 0.07) % 1.0
                    sx_ = int(shaft_s[0] + (shaft_e[0] - shaft_s[0]) * t)
                    sy_ = int(shaft_s[1] + (shaft_e[1] - shaft_s[1]) * t)
                    pygame.draw.circle(surface, (210, 200, 155), (sx_, sy_),
                                       max(1, int(2 * camera.zoom)))
                # Spinning drill bit at tip
                drill_r  = max(3, int(W * 0.55))
                tip_x, tip_y = shaft_e
                for k in range(4):
                    ba  = self._drill_spin + k * (math.pi / 4)
                    bx  = int(tip_x + (-sin_a * math.cos(ba) + cos_a * math.sin(ba)) * drill_r)
                    by_ = int(tip_y + ( cos_a * math.cos(ba) + sin_a * math.sin(ba)) * drill_r)
                    b_col = (235, 220, 160) if k % 2 == 0 else (170, 160, 120)
                    pygame.draw.line(surface, b_col, (tip_x, tip_y), (bx, by_),
                                     max(1, int(2 * camera.zoom)))
                spark_r = max(2, int(W * 0.32 * (0.65 + 0.35 * math.sin(self.time * 16.0))))
                pygame.draw.circle(surface, (255, 210, 80),  shaft_e, spark_r + 1)
                pygame.draw.circle(surface, (255, 255, 200), shaft_e, max(1, spark_r - 1))
            else:
                # Broken drill: red X at tip
                tip_x, tip_y = shaft_e
                arm = max(3, int(W * 0.45))
                pygame.draw.line(surface, (200, 50, 40),
                                 (tip_x - arm, tip_y - arm), (tip_x + arm, tip_y + arm),
                                 max(1, int(2 * camera.zoom)))
                pygame.draw.line(surface, (200, 50, 40),
                                 (tip_x + arm, tip_y - arm), (tip_x - arm, tip_y + arm),
                                 max(1, int(2 * camera.zoom)))
            # Drill health bar (shown only when damaged)
            if drill_frac < 1.0:
                dbar_w = max(12, int(L * 1.8))
                dbx    = int(shaft_s[0] + (shaft_e[0] - shaft_s[0]) * 0.5) - dbar_w // 2
                dby    = int(shaft_s[1] + (shaft_e[1] - shaft_s[1]) * 0.5) - max(8, int(6 * camera.zoom))
                dfill  = max(1, int(dbar_w * drill_frac))
                dc     = (int(220 * (1 - drill_frac)), int(200 * drill_frac), 20)
                pygame.draw.rect(surface, (30, 15, 10),  (dbx, dby, dbar_w, 3))
                pygame.draw.rect(surface, dc,             (dbx, dby, dfill,  3))
                pygame.draw.rect(surface, (160, 80, 60),  (dbx, dby, dbar_w, 3), 1)

        # State dot — grey=idle, green=flying, amber=landed & mining
        dot_col = {'idle': (120, 120, 120), 'to_planet': (80, 210, 80),
                   'landed': (255, 200, 40)}.get(self.state, (128, 128, 128))
        ix = int(cx + cos_a * L * 0.55)
        iy = int(cy + sin_a * L * 0.55)
        pygame.draw.circle(surface, (0, 0, 0), (ix, iy), 4)
        pygame.draw.circle(surface, dot_col,   (ix, iy), 3)

        # Cargo bar: total hold fullness
        total_cargo = sum(self.cargo_hold.values())
        if total_cargo > 0.1:
            _HOLD_CAP = 120.0
            bar_w  = max(16, int(L * 2.4))
            bx     = cx - bar_w // 2
            by     = int(cy - math.hypot(L, W) - 9)
            fill_w = max(1, int(bar_w * min(total_cargo, _HOLD_CAP) / _HOLD_CAP))
            pygame.draw.rect(surface, (30,  30,  30),  (bx, by, bar_w, 4))
            pygame.draw.rect(surface, (70, 210,  90),  (bx, by, fill_w, 4))
            pygame.draw.rect(surface, (160, 160, 160), (bx, by, bar_w, 4), 1)

        # Hull health bar (shown when damaged)
        if self.hp < self.max_hp:
            bar_w  = max(16, int(L * 2.4))
            bx     = cx - bar_w // 2
            by     = int(cy - math.hypot(L, W) - 20)
            hp_f   = self.hp / self.max_hp
            fill_w = max(1, int(bar_w * hp_f))
            hp_col = (int(255 * (1 - hp_f)), int(200 * hp_f), 30)
            pygame.draw.rect(surface, (35, 10, 10),  (bx, by, bar_w, 4))
            pygame.draw.rect(surface, hp_col,         (bx, by, fill_w, 4))
            pygame.draw.rect(surface, (180, 60, 60),  (bx, by, bar_w, 4), 1)


class CargoShip(Entity):
    """
    Seeks the landed MinerShip with the most cargo, beams resources aboard,
    then delivers them to the team's Constructor.
    """

    SPEED       = 380.0
    LOAD_RATE   = 25.0   # units per second drained from miner per material
    UNLOAD_RATE = 35.0   # units per second deposited at constructor per material
    DOCK_RANGE  = 280.0

    # Per-material hold capacities; CARGO_CAP kept for draw-fill reference
    CARGO_CAPS = {
        'iron':     120, 'nickel':   60, 'copper':   80, 'silicon':  60,
        'ice':       80, 'helium3':  60, 'fuel':     80, 'titanium': 60,
        'platinum':  40, 'crystal':  50, 'uranium':  40,
    }
    CARGO_CAP = 120  # = CARGO_CAPS['iron'], used by draw fill

    def __init__(self, wx: float, wy: float, team: int,
                 constructor,
                 miners_ref: list,
                 materials: dict):   # shared ref to team_materials[team]
        color = (160, 255, 180) if team == 0 else (255, 180, 140)
        super().__init__(wx, wy, 52, 26, color)
        self.team              = team
        self.alive             = True
        self.constructor       = constructor
        self._miners_ref       = miners_ref
        self.materials  = materials
        self.cargo_hold = {mat: 0.0 for mat in self.CARGO_CAPS}
        self.state             = 'seeking'
        self._target_miner     = None
        self.vx = self.vy         = 0.0
        self.angle                = 0.0
        self.time                 = 0.0
        self._beam_active         = False
        self._unload_beam_active  = False
        self.max_hp               = 80
        self.hp                   = 80
        self._needs_defense       = False
        self._assigned_miners     = None  # None = auto-seek any miner; list = restricted pool
        self._sep_ax              = 0.0
        self._sep_ay              = 0.0

    def update(self, dt: float) -> None:
        if not self.alive:
            return
        self.time             += dt
        self._beam_active      = False
        self._unload_beam_active = False

        _sm = math.hypot(self._sep_ax, self._sep_ay)
        if _sm > 200.0:
            self._sep_ax *= 200.0 / _sm
            self._sep_ay *= 200.0 / _sm
        self.wx += self._sep_ax * dt
        self.wy += self._sep_ay * dt
        self._sep_ax = 0.0
        self._sep_ay = 0.0

        if self.state == 'seeking':
            # Prune dead miners from the assigned list; fall back to auto if all gone
            if self._assigned_miners is not None:
                self._assigned_miners = [m for m in self._assigned_miners if m.alive]
                if not self._assigned_miners:
                    self._assigned_miners = None
            pool = self._assigned_miners if self._assigned_miners is not None else self._miners_ref
            best       = None
            best_cargo = 8.0
            for m in pool:
                total_cargo = sum(getattr(m, 'cargo_hold', {}).values())
                if (m.team == self.team and m.alive
                        and m.state == 'landed' and total_cargo > best_cargo):
                    best_cargo = total_cargo
                    best       = m
            if best is not None:
                self._target_miner = best
                self.state         = 'to_miner'

        elif self.state == 'to_miner':
            if self._target_miner is None or not self._target_miner.alive:
                self.state = 'seeking'
                return
            # Reassignment happened while en-route — go back and pick the right miner
            if (self._assigned_miners is not None
                    and self._target_miner not in self._assigned_miners):
                self._target_miner = None
                self.state = 'seeking'
                return
            tx = self._target_miner.wx + self._target_miner.width  / 2
            ty = self._target_miner.wy + self._target_miner.height / 2
            self._move_toward(tx, ty, dt)
            if math.hypot(tx - (self.wx + self.width  / 2),
                          ty - (self.wy + self.height / 2)) < self.DOCK_RANGE:
                self.state = 'loading'

        elif self.state == 'loading':
            if self._target_miner is None or not self._target_miner.alive:
                self.state = 'seeking'
                return
            miner_hold = getattr(self._target_miner, 'cargo_hold', {})
            for mat, cap in self.CARGO_CAPS.items():
                avail = miner_hold.get(mat, 0.0)
                xfer  = min(self.LOAD_RATE * dt, avail, cap - self.cargo_hold.get(mat, 0.0))
                if xfer > 0:
                    miner_hold[mat]        -= xfer
                    self.cargo_hold[mat]   += xfer
            self._beam_active = True
            can_transfer = any(
                miner_hold.get(mat, 0.0) > 0.5 and self.cargo_hold.get(mat, 0.0) < cap
                for mat, cap in self.CARGO_CAPS.items()
            )
            if not can_transfer:
                self._beam_active  = False
                self._target_miner = None
                self.state         = 'to_constructor'

        elif self.state == 'to_constructor':
            tx = self.constructor.wx + self.constructor.radius
            ty = self.constructor.wy + self.constructor.radius
            self._move_toward(tx, ty, dt)
            if math.hypot(tx - (self.wx + self.width  / 2),
                          ty - (self.wy + self.height / 2)) < self.DOCK_RANGE:
                self.state = 'depositing'

        elif self.state == 'depositing':
            for mat in list(self.cargo_hold):
                held = self.cargo_hold[mat]
                if held > 0:
                    xfer = min(self.UNLOAD_RATE * dt, held)
                    self.cargo_hold[mat] -= xfer
                    self.materials[mat]   = self.materials.get(mat, 0.0) + xfer
            self._unload_beam_active = True
            if all(v < 0.5 for v in self.cargo_hold.values()):
                for mat in self.cargo_hold:
                    self.cargo_hold[mat] = 0.0
                self._unload_beam_active = False
                self.state               = 'seeking'

    def _move_toward(self, tx: float, ty: float, dt: float) -> None:
        cx   = self.wx + self.width  / 2
        cy   = self.wy + self.height / 2
        dx   = tx - cx
        dy   = ty - cy
        dist = math.hypot(dx, dy)
        if dist > 2.0:
            self.angle = math.atan2(dy, dx)
            spd = self.SPEED if dist > 350 else self.SPEED * (dist / 350)
            self.vx = math.cos(self.angle) * spd
            self.vy = math.sin(self.angle) * spd
        else:
            self.vx = self.vy = 0.0
        self.wx += self.vx * dt
        self.wy += self.vy * dt

    def draw(self, surface: pygame.Surface, camera) -> None:
        if not self.alive:
            return

        # Unload beam: cargo ship → constructor (gold/amber, drawn before vis check)
        if self._unload_beam_active:
            tx = self.constructor.wx + self.constructor.radius
            ty = self.constructor.wy + self.constructor.radius
            bsx, bsy = camera.world_to_screen(
                self.wx + self.width  / 2,
                self.wy + self.height / 2,
            )
            esx, esy = camera.world_to_screen(tx, ty)
            pulse = 0.55 + 0.45 * math.sin(self.time * 10.0)
            lw    = max(2, int(3 * camera.zoom))
            pygame.draw.line(surface, (70, 35, 0),
                             (bsx, bsy), (esx, esy), lw + 3)
            pygame.draw.line(surface,
                             (int(200 + 55 * pulse),
                              int(130 + 70 * pulse),
                              int(10  + 20 * pulse)),
                             (bsx, bsy), (esx, esy), lw)
            pygame.draw.line(surface, (255, 230, 80),
                             (bsx, bsy), (esx, esy), max(1, lw - 1))
            # Crates traveling along the unload beam (ship → constructor)
            _cs = max(3, int(4 * camera.zoom))
            for _ci in range(3):
                _t   = ((self.time * 0.9 + _ci / 3.0) % 1.0)
                _cpx = int(bsx + (esx - bsx) * _t)
                _cpy = int(bsy + (esy - bsy) * _t)
                pygame.draw.rect(surface, (160, 110, 38),
                                 (_cpx - _cs, _cpy - _cs, _cs * 2, _cs * 2))
                pygame.draw.rect(surface, (210, 160, 75),
                                 (_cpx - _cs, _cpy - _cs, _cs * 2, _cs * 2), 1)

        # Load beam: miner → cargo ship (green, drawn before vis check)
        if self._beam_active and self._target_miner is not None:
            mx  = self._target_miner.wx + self._target_miner.width  / 2
            my  = self._target_miner.wy + self._target_miner.height / 2
            bsx, bsy = camera.world_to_screen(mx, my)
            esx, esy = camera.world_to_screen(
                self.wx + self.width  / 2,
                self.wy + self.height / 2,
            )
            pulse = 0.55 + 0.45 * math.sin(self.time * 14.0)
            lw    = max(2, int(3 * camera.zoom))
            pygame.draw.line(surface, (10, 60, 10),
                             (bsx, bsy), (esx, esy), lw + 3)
            pygame.draw.line(surface,
                             (int(60  + 100 * pulse),
                              int(200 +  55 * pulse),
                              int(60  + 100 * pulse)),
                             (bsx, bsy), (esx, esy), lw)
            pygame.draw.line(surface, (210, 255, 210),
                             (bsx, bsy), (esx, esy), max(1, lw - 1))
            # Crates traveling along the loading beam (miner → ship)
            _cs = max(3, int(4 * camera.zoom))
            for _ci in range(3):
                _t   = ((self.time * 1.1 + _ci / 3.0) % 1.0)
                _cpx = int(bsx + (esx - bsx) * _t)
                _cpy = int(bsy + (esy - bsy) * _t)
                pygame.draw.rect(surface, (60, 150, 70),
                                 (_cpx - _cs, _cpy - _cs, _cs * 2, _cs * 2))
                pygame.draw.rect(surface, (140, 220, 140),
                                 (_cpx - _cs, _cpy - _cs, _cs * 2, _cs * 2), 1)

        if not camera.is_visible(self.world_rect):
            return

        cx, cy = camera.world_to_screen(
            self.wx + self.width  / 2,
            self.wy + self.height / 2,
        )
        cos_a = math.cos(self.angle)
        sin_a = math.sin(self.angle)
        L = self.width  / 2 * camera.zoom
        W = self.height / 2 * camera.zoom

        def ts(lx, ly):
            return (int(cx + lx * cos_a - ly * sin_a),
                    int(cy + lx * sin_a + ly * cos_a))

        fill   = min(self.cargo_hold.get('iron', 0) / self.CARGO_CAP, 1.0)
        active = self.state in ('loading', 'depositing')
        pulse  = (0.72 + 0.28 * math.sin(self.time * 8.0)) if active else 1.0

        # ── Cargo hold interior (drawn first, behind the hull) ────────────
        hold_pts = [
            ts( L * 0.32,  W * 0.66),
            ts(-L * 0.22,  W * 0.80),
            ts(-L * 0.70,  W * 0.70),
            ts(-L * 0.86,  0        ),
            ts(-L * 0.70, -W * 0.70),
            ts(-L * 0.22, -W * 0.80),
            ts( L * 0.32, -W * 0.66),
        ]
        # Empty → dark blue-grey; Full → bright amber-gold
        hr = int(22  + 233 * fill * pulse)
        hg = int(18  + 152 * fill * pulse)
        hb = int(38  -  18 * fill)
        pygame.draw.polygon(surface,
                            (min(255, hr), min(255, hg), max(0, hb)),
                            hold_pts)

        # Four cargo-level indicator dots along the hold (back → front)
        n_pips = 4
        for i in range(n_pips):
            lit   = fill >= (i + 1) / n_pips
            t_pos = -L * 0.65 + L * 1.1 * (i / (n_pips - 1))
            # screen position of the dot (offset perpendicular to heading)
            pip_pulse = pulse if (active and lit) else 1.0
            pip_col   = (
                min(255, int(60  + 195 * lit * pip_pulse)),
                min(255, int(45  + 130 * lit * pip_pulse)),
                int(8 * lit),
            ) if lit else (28, 28, 38)
            r_pip = max(2, int(2.5 * camera.zoom))
            for sign in (-1, 1):
                px = int(cx + cos_a * t_pos - sin_a * (W * 0.52 * sign))
                py = int(cy + sin_a * t_pos + cos_a * (W * 0.52 * sign))
                pygame.draw.circle(surface, (0, 0, 0), (px, py), r_pip + 1)
                pygame.draw.circle(surface, pip_col,   (px, py), r_pip)

        # ── Outer hull ───────────────────────────────────────────────────
        hull_pts = [
            ts( L,         0        ),
            ts( L * 0.50,  W * 0.88 ),
            ts(-L * 0.20,  W        ),
            ts(-L * 0.68,  W * 0.90 ),
            ts(-L,         W * 0.40 ),
            ts(-L,        -W * 0.40 ),
            ts(-L * 0.68, -W * 0.90 ),
            ts(-L * 0.20, -W        ),
            ts( L * 0.50, -W * 0.88 ),
        ]
        pygame.draw.polygon(surface, self.color, hull_pts)
        rim_col = (int(255 * pulse), int(220 * pulse), 80) if (active and fill > 0.05) \
                  else (180, 180, 180)
        pygame.draw.polygon(surface, rim_col, hull_pts, 1)

        # ── Cargo crates attached to hull sides ───────────────────────────
        if fill > 0.01:
            crate_lxs = [-L * 0.64, -L * 0.34, -L * 0.04, L * 0.19]
            cw = L * 0.13   # half-width along ship axis
            ch = W * 0.20   # half-height perpendicular
            for i, clx in enumerate(crate_lxs):
                if fill < (i + 1) / 4:
                    continue
                cp = pulse if active else 1.0
                crate_col = (
                    min(255, int((100 + 100 * fill) * cp)),
                    min(255, int((70  +  70 * fill) * cp)),
                    int(15  *  (1 - fill)),
                )
                rim_c = (min(255, crate_col[0] + 45),
                         min(255, crate_col[1] + 35),
                         min(255, crate_col[2] + 8))
                border_w = max(1, int(camera.zoom * 0.8))
                for sign in (-1, 1):
                    cly = W * 1.02 * sign
                    pts = [
                        ts(clx - cw, cly - ch),
                        ts(clx + cw, cly - ch),
                        ts(clx + cw, cly + ch),
                        ts(clx - cw, cly + ch),
                    ]
                    pygame.draw.polygon(surface, crate_col, pts)
                    pygame.draw.polygon(surface, rim_c, pts, border_w)

        # ── Stacked crates on hull top (grows with fill) ─────────────────
        _total_held = sum(self.cargo_hold.values())
        _total_cap  = sum(self.CARGO_CAPS.values())
        _total_fill = min(_total_held / max(1.0, _total_cap), 1.0)
        _n_stack    = int(_total_fill * 5)  # 0–5 crates

        if _n_stack > 0:
            _cw  = max(4, int(L * 0.36))
            _ch  = max(3, int(_cw * 0.62))
            _gap = max(1, int(camera.zoom))
            _crate_base_cols = [
                (130,  88, 38), (118,  78, 32), (142,  98, 44),
                (122,  82, 36), (135,  92, 41),
            ]
            for _i in range(_n_stack):
                _ly  = -(W * 1.05 + _gap + _i * (_ch * 2 + _gap) + _ch)
                _cc  = _crate_base_cols[_i % len(_crate_base_cols)]
                _rc  = tuple(min(255, c + 48) for c in _cc)
                _cpts = [
                    ts(-_cw, _ly - _ch),
                    ts( _cw, _ly - _ch),
                    ts( _cw, _ly + _ch),
                    ts(-_cw, _ly + _ch),
                ]
                pygame.draw.polygon(surface, _cc, _cpts)
                pygame.draw.polygon(surface, _rc, _cpts,
                                    max(1, int(camera.zoom * 0.8)))
                # Binding strap across the middle
                pygame.draw.line(surface, _rc,
                                 ts(-_cw * 0.85, _ly), ts(_cw * 0.85, _ly),
                                 max(1, int(camera.zoom * 0.7)))

        # Engine glow at stern
        eng_px = int(cx - cos_a * L)
        eng_py = int(cy - sin_a * L)
        r_eng  = max(2, int(W * 0.38))
        ep     = 0.6 + 0.4 * math.sin(self.time * 5.5 + 1.2)
        pygame.draw.circle(surface,
                           (int(70 * ep), int(110 * ep), int(255 * ep)),
                           (eng_px, eng_py), r_eng + 1)
        pygame.draw.circle(surface, (160, 200, 255), (eng_px, eng_py), max(1, r_eng - 1))

        # ── State dot ────────────────────────────────────────────────────
        _state_col = {
            'seeking':        (160, 160, 160),
            'to_miner':       (80,  210,  80),
            'loading':        (80,  255, 120),
            'to_constructor': (80,  160, 255),
            'depositing':     (255, 200,  40),
        }
        dot_col = _state_col.get(self.state, (128, 128, 128))
        ix = int(cx + cos_a * L * 0.48)
        iy = int(cy + sin_a * L * 0.48)
        pygame.draw.circle(surface, (0, 0, 0), (ix, iy), 4)
        pygame.draw.circle(surface, dot_col,   (ix, iy), 3)

        # Purple hull aura when carrying crystal
        _crystal_held = self.cargo_hold.get('crystal', 0)
        if _crystal_held > 0.5:
            s_fill  = min(_crystal_held / self.CARGO_CAPS.get('crystal', 50), 1.0)
            sp      = (0.65 + 0.35 * math.sin(self.time * 7.0)) if active else 0.8
            r_aura  = max(5, int(math.hypot(L, W) * 1.15))
            for step in range(3, 0, -1):
                frac = step / 3
                gc = (int(120 * frac * s_fill * sp),
                      int(30  * frac * s_fill * sp),
                      int(180 * frac * s_fill * sp))
                pygame.draw.circle(surface, gc, (cx, cy), int(r_aura * frac))

        # ── Cargo bars above the ship ─────────────────────────────────────
        _total_held = sum(self.cargo_hold.values())
        if _total_held > 0.1:
            _total_cap = sum(self.CARGO_CAPS.values())
            bar_w  = max(20, int(L * 2.6))
            bx     = cx - bar_w // 2
            by     = int(cy - math.hypot(L, W) - 12)
            # Primary bar: total fill
            tf     = min(_total_held / _total_cap, 1.0)
            fill_w = max(1, int(bar_w * tf))
            bc     = (min(255, int(80 + 175 * tf)), min(255, int(200 - 40 * tf)), 20)
            pygame.draw.rect(surface, (25, 25, 25),   (bx, by, bar_w, 5))
            pygame.draw.rect(surface, bc,              (bx, by, fill_w, 5))
            pygame.draw.rect(surface, (140, 140, 140), (bx, by, bar_w, 5), 1)
            # Secondary bar: crystal (purple) if present
            if _crystal_held > 0.5:
                s_f    = min(_crystal_held / self.CARGO_CAPS.get('crystal', 50), 1.0)
                s_fill = max(1, int(bar_w * s_f))
                sy_bar = by + 7
                pygame.draw.rect(surface, (20,  10,  35),  (bx, sy_bar, bar_w, 5))
                pygame.draw.rect(surface, (180,  80, 255), (bx, sy_bar, s_fill, 5))
                pygame.draw.rect(surface, (140, 100, 200), (bx, sy_bar, bar_w, 5), 1)

        # Hull health bar (shown when damaged)
        if self.hp < self.max_hp:
            bar_w  = max(20, int(L * 2.6))
            bx     = cx - bar_w // 2
            by     = int(cy - math.hypot(L, W) - 24)
            hp_f   = self.hp / self.max_hp
            fill_w = max(1, int(bar_w * hp_f))
            hp_col = (int(255 * (1 - hp_f)), int(200 * hp_f), 30)
            pygame.draw.rect(surface, (35, 10, 10),  (bx, by, bar_w, 5))
            pygame.draw.rect(surface, hp_col,         (bx, by, fill_w, 5))
            pygame.draw.rect(surface, (180, 60, 60),  (bx, by, bar_w, 5), 1)

    @property
    def hit_chance(self) -> float:
        return 0.65

    def take_damage(self, amount: int) -> None:
        self.hp -= amount
        if self.hp <= 0:
            self.hp    = 0
            self.alive = False

    def try_take_damage(self, amount: int) -> bool:
        if random.random() < self.hit_chance:
            self.take_damage(amount)
            return True
        return False


class GlowingAsteroid:
    """
    A static, glowing space rock.  Position never changes; only the pulse
    and glow are animated each frame.
    """

    _GLOW_PALETTE = [
        (80,  200, 255),   # icy blue-white
        (255, 200,  80),   # amber
        (120, 255, 140),   # pale green
        (200, 110, 255),   # violet
        (255, 130, 100),   # orange-red
    ]

    planet_type = 'glowing'
    team        = None            # neutral — any miner can target it

    def __init__(self, wx: float, wy: float):
        self.radius = random.randint(55, 120)
        self.wx     = wx - self.radius   # store top-left so wx+radius == center
        self.wy     = wy - self.radius
        self.width  = self.radius * 2
        self.height = self.radius * 2
        self.angle  = random.uniform(0.0, math.tau)
        self.time   = random.uniform(0.0, 12.0)   # phase offset so each rock pulses differently
        self.alive         = True
        self.resources     = float(self.radius * 8)   # 440–960 special units
        self.max_resources = self.resources

        n = random.randint(7, 11)
        self._shape = []
        for i in range(n):
            a = i * math.tau / n + random.uniform(-0.25, 0.25)
            r = self.radius * random.uniform(0.55, 1.0)
            self._shape.append((math.cos(a) * r, math.sin(a) * r))

        self.glow_color  = random.choice(self._GLOW_PALETTE)
        self._rock_color = (168, 162, 155)
        self._rock_rim   = (210, 205, 200)
        # Set yields based on asteroid type (glowing asteroids)
        self.yields = {'crystal': 5.0, 'platinum': 3.0}

    def update(self, dt: float) -> None:
        self.time += dt

    def draw(self, surface: pygame.Surface, camera) -> None:
        if not self.alive:
            return
        pad = self.radius
        if not camera.is_visible_xywh(self.wx - pad, self.wy - pad, pad * 2, pad * 2):
            return

        sx, sy = camera.world_to_screen(self.wx + self.radius, self.wy + self.radius)
        zoom   = camera.zoom
        res_frac = max(0.0, self.resources / self.max_resources)
        pulse  = (0.5 + 0.5 * math.sin(self.time * 1.6)) * res_frac
        r_scr  = max(2, int(self.radius * zoom))

        # Outer glow rings (fade as resource depletes)
        for step in range(5, 0, -1):
            glow_r = r_scr + int(step * 9 * zoom)
            frac   = (step / 5) * pulse * 0.45
            gc = (
                int(self.glow_color[0] * frac),
                int(self.glow_color[1] * frac),
                int(self.glow_color[2] * frac),
            )
            if glow_r > 1:
                pygame.draw.circle(surface, gc, (sx, sy), glow_r)

        # Rock body (greyer when nearly depleted)
        grey_blend = 1.0 - res_frac * 0.5
        rock_col = (
            int(self._rock_color[0] * grey_blend + 80 * (1 - grey_blend)),
            int(self._rock_color[1] * grey_blend + 80 * (1 - grey_blend)),
            int(self._rock_color[2] * grey_blend + 80 * (1 - grey_blend)),
        )
        cos_a = math.cos(self.angle)
        sin_a = math.sin(self.angle)
        pts   = [
            (sx + int((lx * cos_a - ly * sin_a) * zoom),
             sy + int((lx * sin_a + ly * cos_a) * zoom))
            for lx, ly in self._shape
        ]
        if len(pts) >= 3:
            pygame.draw.polygon(surface, rock_col,       pts)
            pygame.draw.polygon(surface, self._rock_rim, pts, max(1, int(zoom)))

        # Bright core (dims as resource depletes)
        core_r = max(2, int(r_scr * 0.28))
        core_c = tuple(min(255, int(c * (0.6 + 0.4 * pulse) * res_frac)) for c in self.glow_color)
        pygame.draw.circle(surface, core_c, (sx, sy), core_r)

        # Resource bar below the rock
        if res_frac < 1.0:
            bar_w  = max(10, int(r_scr * 2.0))
            bar_h  = max(2, int(3 * zoom))
            bar_x  = sx - bar_w // 2
            bar_y  = sy + r_scr + max(3, int(4 * zoom))
            fill_w = max(0, int(bar_w * res_frac))
            pygame.draw.rect(surface, (60, 0, 80),  (bar_x, bar_y, bar_w,  bar_h))
            pygame.draw.rect(surface, tuple(min(255, c) for c in self.glow_color),
                             (bar_x, bar_y, fill_w, bar_h))


class MineableAsteroid:
    """
    A large, interactable asteroid visible above the background.
    Any miner can land on it to gather regular resources.
    """

    MINE_RATE   = 3.5
    planet_type = 'asteroid'
    team        = None

    def __init__(self, wx: float, wy: float):
        self.wx     = wx
        self.wy     = wy
        self.radius = random.randint(70, 140)
        self.width  = self.radius * 2
        self.height = self.radius * 2
        self.alive         = True
        self.time          = 0.0
        self.resources     = float(self.radius * 10)   # 700–1400 ore units
        self.max_resources = self.resources

        n = random.randint(7, 11)
        self._shape = []
        for i in range(n):
            a = i * math.tau / n + random.uniform(-0.3, 0.3)
            r = self.radius * random.uniform(0.60, 1.0)
            self._shape.append((math.cos(a) * r, math.sin(a) * r))

        self._col_fill = (138, 132, 124)
        self._col_rim  = (195, 190, 185)
        # Set yields based on asteroid type (mineable/normal asteroids)
        self.yields = {'titanium': 8.0, 'uranium': 4.0}

    def update(self, dt: float) -> None:
        pass

    def draw(self, surface: pygame.Surface, camera) -> None:
        if not self.alive:
            return
        pad = self.radius
        if not camera.is_visible_xywh(self.wx - pad, self.wy - pad, pad * 2, pad * 2):
            return
        cx, cy = camera.world_to_screen(self.wx + self.radius, self.wy + self.radius)
        z      = camera.zoom
        res_frac = max(0.0, self.resources / self.max_resources)

        # Rock fill dims as ore runs out
        fill_col = (
            int(self._col_fill[0] * res_frac + 60 * (1 - res_frac)),
            int(self._col_fill[1] * res_frac + 60 * (1 - res_frac)),
            int(self._col_fill[2] * res_frac + 55 * (1 - res_frac)),
        )
        pts = [
            (int(cx + lx * z), int(cy + ly * z))
            for lx, ly in self._shape
        ]
        if len(pts) >= 3:
            pygame.draw.polygon(surface, fill_col,     pts)
            pygame.draw.polygon(surface, self._col_rim, pts, max(1, int(2 * z)))
        # Outer ring
        r_out = max(4, int(self.radius * z * 1.12))
        pygame.draw.circle(surface, (170, 165, 160), (cx, cy), r_out, max(1, int(z)))
        # Pickaxe cross (hidden once fully depleted)
        if res_frac > 0.05:
            arm = max(4, int(self.radius * z * 0.25))
            cross_col = (int(220 * res_frac + 80 * (1 - res_frac)),
                         int(210 * res_frac + 80 * (1 - res_frac)),
                         int(200 * res_frac + 80 * (1 - res_frac)))
            pygame.draw.line(surface, cross_col, (cx - arm, cy), (cx + arm, cy), max(1, int(z)))
            pygame.draw.line(surface, cross_col, (cx, cy - arm), (cx, cy + arm), max(1, int(z)))
        # Resource bar
        r_scr  = max(4, int(self.radius * z))
        bar_w  = max(10, int(r_scr * 2.0))
        bar_h  = max(2, int(3 * z))
        bar_x  = cx - bar_w // 2
        bar_y  = cy + r_out + max(3, int(4 * z))
        fill_px = max(0, int(bar_w * res_frac))
        pygame.draw.rect(surface, (50, 35, 20),   (bar_x, bar_y, bar_w,  bar_h))
        pygame.draw.rect(surface, (200, 160, 60), (bar_x, bar_y, fill_px, bar_h))


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

    # ── Team-level strategic state ──────────────────────────────────────────
    # Recomputed once per frame by main.py (cheap aggregate stats), then read
    # by every ship's update_combat — avoids each ship re-scanning the fleet.
    team_strength_ratio: dict = {0: 1.0, 1: 1.0}   # own_hp_total / enemy_hp_total per team
    team_focus_fleet:    dict = {0: None, 1: None}  # team -> enemy fleet_leader to mass fire on
    REGROUP_ALLY_RADIUS = 700.0   # consider a ship "isolated" with no allies within this range

    # World bounds — overwritten by main.py once the map size is known, so
    # edge-avoidance and "cornered" detection share the game's real dimensions.
    WORLD_W = 16000.0
    WORLD_H = 12800.0
    EDGE_MARGIN   = 600.0   # start steering away from a wall this far out
    CORNER_MARGIN = 300.0   # this close to a wall with an enemy nearby = no room left to flee

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
            big  = w >= 66
        else:
            big = random.random() > 0.5
            if big:
                w = 87
                h = 42
            else:
                w = 48
                h = 24

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
        self._lat_vel            = 0.0  # lateral velocity (perpendicular to heading) for side thrusters
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

        # Player command state — set/cleared by main.py in response to player orders
        self.player_hold = False   # True: hold this exact spot (still aims/fires)
        self.hold_fire   = False   # True: weapons disabled regardless of targets in range

        # Deployment — both teams start parked at their spawn and hold there
        # (still fight back if attacked) until their commander — the player
        # via orders, or the AICommander via a fleet-wide push — deploys them.
        self.deployed = False
        self.home_pos = (wx + self.width / 2, wy + self.height / 2)

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

            if self._movement_override is None:
                # Waypoint travel: smooth decel on approach to a fixed point
                if dist < self.DECEL_DIST:
                    desired_speed = self.max_speed * (dist / self.DECEL_DIST)
                    self._dampening = True
                else:
                    desired_speed = self.max_speed
                    self._thrusting = True
            else:
                # Combat override: always full thrust — the target point moves every
                # frame so a decel zone would oscillate desired speed each frame
                desired_speed = self.max_speed
                self._thrusting = True

            desired_vx = math.cos(target_angle) * desired_speed
            desired_vy = math.sin(target_angle) * desired_speed
        else:
            desired_vx, desired_vy = 0.0, 0.0

        # Smoothly steer velocity toward the desired value
        t = min(1.0, 6.0 * dt)
        self.vx += (desired_vx - self.vx) * t
        self.vy += (desired_vy - self.vy) * t

        # Apply separation impulse — cap so clustered ships can't spike huge combined forces
        sep_mag = math.hypot(self._sep_ax, self._sep_ay)
        if sep_mag > 120.0:
            self._sep_ax *= 120.0 / sep_mag
            self._sep_ay *= 120.0 / sep_mag
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

        # Side thrusters cancel lateral drift (velocity perpendicular to ship heading)
        # right-hand perpendicular of heading: (sin_a, -cos_a)
        cos_a = math.cos(self.angle)
        sin_a = math.sin(self.angle)
        v_lat = self.vx * sin_a - self.vy * cos_a   # + = drifting right of heading
        SIDE_DAMP = 2.5                              # gentle — avoids overcorrection oscillation
        remove = v_lat * min(1.0, SIDE_DAMP * dt)
        self.vx -= remove * sin_a
        self.vy += remove * cos_a
        self._lat_vel = v_lat

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

        # ── Retreat: break off when critically damaged ────────────────────
        # Adaptive aggression: a team that's winning presses the advantage
        # (retreats later); a losing team breaks off earlier to preserve hulls.
        team_ratio        = self.team_strength_ratio.get(self.team, 1.0)
        retreat_threshold = RETREAT_HP_RATIO * max(0.6, min(1.8, 1.0 / max(0.01, team_ratio)))
        if self.hp / self.max_hp < retreat_threshold:
            self.combat_state       = 'retreat'
            self._current_target    = None
            self._movement_override = self._calc_retreat_pos(cx, cy, all_ships)
            self._aim_and_fire(dt, cx, cy, all_ships, lasers)
            return

        # ── Player hold: stay locked in place, still fight back ───────────
        if self.player_hold:
            self.combat_state       = 'engage' if self._has_target else 'patrol'
            self._movement_override = (cx, cy)
            self._aim_and_fire(dt, cx, cy, all_ships, lasers)
            return

        # ── Target selection with team coordination ───────────────────────
        # Count how many living allies are currently engaging each enemy so
        # ships can spread fire across multiple targets instead of pile-driving one.
        target_counts: dict[int, int] = {}
        for ship in all_ships:
            _tgt = getattr(ship, '_current_target', None)
            if ship.team == self.team and ship.alive and _tgt is not None:
                target_counts[id(_tgt)] = target_counts.get(id(_tgt), 0) + 1

        focus_fleet = self.team_focus_fleet.get(self.team)

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
            # Fleet commander: mass fire on whichever enemy fleet is weakest
            if focus_fleet is not None and getattr(ship, 'fleet_leader', None) is focus_fleet:
                score -= 300.0
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
                # No task assigned (no order, no commander push): patrol the
                # home solar system on the waypoint loop instead of holding
                # still or wandering off across the whole map.
                self._movement_override = None
            return

        # ── Positional tactics: don't let lone ships overextend ───────────
        # If we're still some way from the target and no ally is nearby,
        # regroup toward the fleet slot first rather than charging in solo.
        target_dist = math.hypot(
            (best_target.wx + best_target.width / 2) - cx,
            (best_target.wy + best_target.height / 2) - cy,
        )
        isolated = target_dist > self.attack_range * 0.8 and not any(
            ship is not self and ship.team == self.team and ship.alive
            and math.hypot((ship.wx + ship.width / 2) - cx,
                            (ship.wy + ship.height / 2) - cy) < self.REGROUP_ALLY_RADIUS
            for ship in all_ships
        )
        if (isolated and self.fleet_leader is not None and self.fleet_leader is not self
                and self.fleet_leader.alive):
            self.combat_state = 'patrol'
            lcx = self.fleet_leader.wx + self.fleet_leader.width  / 2
            lcy = self.fleet_leader.wy + self.fleet_leader.height / 2
            self._movement_override = (lcx + self.fleet_offset[0],
                                       lcy + self.fleet_offset[1])
            self._aim_and_fire(dt, cx, cy, all_ships, lasers)
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

    def _edge_push(self, cx: float, cy: float) -> tuple[float, float]:
        """Repulsion vector pushing away from nearby world-boundary walls,
        scaled 0→1 by how deep into the margin the ship has drifted."""
        push_x = push_y = 0.0
        if cx < self.EDGE_MARGIN:
            push_x += (self.EDGE_MARGIN - cx) / self.EDGE_MARGIN
        elif cx > self.WORLD_W - self.EDGE_MARGIN:
            push_x -= (self.EDGE_MARGIN - (self.WORLD_W - cx)) / self.EDGE_MARGIN
        if cy < self.EDGE_MARGIN:
            push_y += (self.EDGE_MARGIN - cy) / self.EDGE_MARGIN
        elif cy > self.WORLD_H - self.EDGE_MARGIN:
            push_y -= (self.EDGE_MARGIN - (self.WORLD_H - cy)) / self.EDGE_MARGIN
        return push_x, push_y

    def _calc_retreat_pos(self, cx: float, cy: float, all_ships: list) -> tuple[float, float]:
        """Return a flee destination directly away from the nearest enemy,
        curved off nearby walls — or, if pinned in a corner with no room
        left to run, a charge straight at that enemy as a last-ditch ram."""
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

        # Cornered: a wall is right behind us and the enemy is already close
        # enough that there's no time to route around it — going down
        # fighting beats being picked apart while pinned, so ram the threat.
        dist_to_edge = min(cx, cy, self.WORLD_W - cx, self.WORLD_H - cy)
        if dist_to_edge < self.CORNER_MARGIN and nearest_dist < self.attack_range * 1.3:
            self.combat_state = 'engage'
            return (ex, ey)

        # Otherwise curve the flee heading off nearby walls so retreating
        # ships bend back toward open space instead of running into one.
        push_x, push_y = self._edge_push(cx, cy)
        fx, fy = dx + push_x, dy + push_y
        fmag = math.hypot(fx, fy)
        if fmag > 0:
            dx, dy = fx / fmag, fy / fmag
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
        if self.hold_fire:
            self._has_target = False
            return
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

        cos_a = math.cos(self.angle)
        sin_a = math.sin(self.angle)

        if self._thrusting and sp > 5.0:
            # Main engine exhaust fires from the stern along the ship's rear axis
            rear_ang = self.angle + math.pi   # pointing straight back
            for _ in range(2):
                ang   = rear_ang + random.gauss(0, 0.22)
                spd   = random.uniform(sp * 0.40, sp * 0.95)
                max_a = random.uniform(0.15, 0.32)
                r0    = self.height * random.uniform(0.10, 0.30)
                self._thruster_particles.append([
                    cx - cos_a * self.width * 0.44,   # stern position
                    cy - sin_a * self.width * 0.44,
                    math.cos(ang) * spd,
                    math.sin(ang) * spd,
                    0.0, max_a, r0, 0,
                ])

        if self._dampening and sp > 5.0:
            # Bow-side thrusters fire forward along the ship heading to brake
            for sign in (1.0, -1.0):
                # Front corners of the ship based on heading, not velocity
                jx    = cx + cos_a * self.width * 0.30 + sin_a * self.height * 0.50 * sign
                jy    = cy + sin_a * self.width * 0.30 - cos_a * self.height * 0.50 * sign
                spd   = random.uniform(sp * 0.10, sp * 0.35)
                ang   = self.angle + random.gauss(0, 0.20)   # exhaust fires forward = thrust brakes
                max_a = random.uniform(0.10, 0.22)
                r0    = self.height * random.uniform(0.05, 0.15)
                self._thruster_particles.append([
                    jx, jy,
                    math.cos(ang) * spd,
                    math.sin(ang) * spd,
                    0.0, max_a, r0, 1,
                ])

        # Side RCS thrusters cancel lateral drift relative to ship heading
        lat = self._lat_vel
        if sp > 5.0 and abs(lat) > 8.0:
            # The drifting side fires exhaust outward to push back against drift
            side = 1.0 if lat > 0 else -1.0
            # Spawn two ports along the ship length (front-third and rear-third)
            for frac in (0.30, -0.30):
                port_x = cx + cos_a * self.width * frac + sin_a * self.height * 0.50 * side
                port_y = cy + sin_a * self.width * frac - cos_a * self.height * 0.50 * side
                # Exhaust fires outward from the ship side
                exhaust_ang = math.atan2(-cos_a * side, sin_a * side)
                lat_sp = abs(lat)
                ang    = exhaust_ang + random.gauss(0, 0.18)
                spd    = random.uniform(lat_sp * 0.20, lat_sp * 0.60)
                max_a  = random.uniform(0.08, 0.16)
                r0     = self.height * random.uniform(0.04, 0.11)
                self._thruster_particles.append([
                    port_x, port_y,
                    math.cos(ang) * spd,
                    math.sin(ang) * spd,
                    0.0, max_a, r0, 2,
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
            elif p[7] == 1: # dampener: cyan → blue → dark
                col = (
                    int(30  * t),
                    int(140 * t * t),
                    min(255, int(240 * t + 15)),
                )
            else:            # RCS side thruster: bright white-violet puff
                col = (
                    min(255, int(200 * t + 55 * t * t)),
                    min(255, int(160 * t * t + 40 * t)),
                    min(255, int(255 * t)),
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

    LAUNCH_DURATION = 2.2    # seconds for catapult roll and climb-out
    DOCK_RADIUS     = 185.0  # unused legacy — kept for reference
    LAND_RANGE      = 160.0  # world units from carrier centre to trigger landing sequence
    LAND_DURATION   = 0.75   # seconds the landing slide animation plays
    RETURN_IDLE_T   = 9.0    # seconds without a target before starting return approach

    def __init__(self, wx: float, wy: float, waypoints: list[tuple[float, float]],
                 team: int, home_carrier=None):
        w = 18
        h = 10
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
        self._landing_t    = -1.0   # -1 = not landing; ≥0 = landing slide in progress
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
            return

        if self._landing_t >= 0:
            # Landing slide: lock heading to carrier, bleed off speed, then dock
            self._landing_t += dt
            if self.home_carrier is not None:
                self.angle = self.home_carrier.angle
            decel = max(0.0, 1.0 - 7.0 * dt)
            self.vx *= decel
            self.vy *= decel
            self.wx += self.vx * dt
            self.wy += self.vy * dt
            self._emit_particles(dt)
            if self._landing_t >= self.LAND_DURATION:
                self.alive = False
            return

        if self._returning and self.home_carrier is not None and self.home_carrier.alive:
            hcx = self.home_carrier.wx + self.home_carrier.width  / 2
            hcy = self.home_carrier.wy + self.home_carrier.height / 2
            fx  = self.wx + self.width  / 2
            fy  = self.wy + self.height / 2
            dist = math.hypot(fx - hcx, fy - hcy)
            # Trigger landing slide once the fighter is close to the carrier hull
            if dist < self.LAND_RANGE:
                self._landing_t = 0.0
                return
            super().update(dt)
        else:
            if self._returning:
                self._returning = False   # carrier is gone; fight independently
            super().update(dt)

    def update_combat(self, dt: float, all_ships: list, lasers: list) -> None:
        if self._launch_t > 0 or self._landing_t >= 0:
            return   # weapons hold during launch roll and landing slide

        # ── Returning to carrier ──────────────────────────────────────────────
        if self._returning:
            if self.home_carrier is None or not self.home_carrier.alive:
                self._returning = False   # carrier destroyed; fight on
            else:
                hcx   = self.home_carrier.wx + self.home_carrier.width  / 2
                hcy   = self.home_carrier.wy + self.home_carrier.height / 2
                cos_c = math.cos(self.home_carrier.angle)
                sin_c = math.sin(self.home_carrier.angle)
                fx    = self.wx + self.width  / 2
                fy    = self.wy + self.height / 2
                # Dot product: positive means fighter is ahead of carrier, negative = behind
                ahead = (fx - hcx) * cos_c + (fy - hcy) * sin_c
                if ahead > -self.home_carrier.width * 0.25:
                    # Fighter is in front of or beside the carrier — route to a
                    # waypoint well behind the stern so it loops around properly
                    self._movement_override = (
                        hcx - cos_c * (self.home_carrier.width * 0.5 + 280),
                        hcy - sin_c * (self.home_carrier.width * 0.5 + 280),
                    )
                else:
                    # Fighter is behind the carrier — fly straight in to the deck
                    self._movement_override = (hcx, hcy)
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

    MAX_FIGHTERS    = 15     # maximum active fighters per carrier
    DEPLOY_INTERVAL = 10.0   # seconds between fighter deployments

    # Six possible AA turret positions around the hull perimeter (lx_frac, ly_frac)
    _AA_POSITIONS = [
        ( 0.55, -0.45), ( 0.55,  0.45),   # fore port / starboard
        (-0.05, -0.52), (-0.05,  0.52),   # mid  port / starboard
        (-0.65, -0.42), (-0.65,  0.42),   # aft  port / starboard
    ]

    def __init__(self, wx: float, wy: float, waypoints: list[tuple[float, float]],
                 team: int):
        w = 270
        h = 112
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

        # Signal allied ships when the carrier is threatened — either an enemy
        # is closing in, or our hull is already badly damaged and needs escorts
        # to fall back and cover us regardless of where the threat currently is.
        SAFE_DIST    = ATTACK_RANGE * 1.8
        hp_ratio      = self.hp / self.max_hp
        self._needs_defense = (
            (nearest_enemy is not None and nearest_dist < SAFE_DIST)
            or hp_ratio < 0.5
        )

        # Movement: hang back at a safe distance — never charge the front line
        if nearest_enemy is not None and nearest_dist < SAFE_DIST:
            self.combat_state = 'retreat'
            ex = nearest_enemy.wx + nearest_enemy.width  / 2
            ey = nearest_enemy.wy + nearest_enemy.height / 2
            dx, dy = cx - ex, cy - ey
            d = math.hypot(dx, dy)
            if d > 0:
                dx, dy = dx / d, dy / d
            # Curve the flee heading off nearby walls — carriers never
            # charge, so without this they just pin themselves to the edge.
            push_x, push_y = self._edge_push(cx, cy)
            fx, fy = dx + push_x, dy + push_y
            fmag = math.hypot(fx, fy)
            if fmag > 0:
                dx, dy = fx / fmag, fy / fmag
            self._movement_override = (cx + dx * 700, cy + dy * 700)
        else:
            self.combat_state       = 'patrol'
            # No task assigned: patrol the home solar system on the waypoint
            # loop. Leave the override clear so a commander rally-point order
            # (applied after update_combat) can still take over when given.
            self._movement_override = None

        # AA guns fire at enemies that get within AA_RANGE
        self._aim_and_fire(dt, cx, cy, all_ships, lasers)

        # ── Fighter deployment ─────────────────────────────────────────────
        # Prune dead fighters from the active list
        self._active_fighters = [f for f in self._active_fighters if f.alive]
        live_count = len(self._active_fighters)

        enemy_detected    = nearest_enemy is not None and nearest_dist < ATTACK_RANGE * 2.2
        under_direct_fire = nearest_dist < AA_RANGE * 1.5

        # Reserve doctrine: only commit a fraction of the squadron proactively
        # while quiet, so a surprise attack always has fresh fighters to scramble.
        # The reserve cap lifts entirely once a real threat is detected.
        deploy_cap = self.MAX_FIGHTERS if enemy_detected else int(self.MAX_FIGHTERS * 0.6)

        self._deploy_timer -= dt

        if enemy_detected and live_count < deploy_cap:
            # Emergency scramble: bypass timer when enemy is dangerously close
            # and we have fewer than half our fighters up
            if under_direct_fire and live_count < self.MAX_FIGHTERS // 2:
                self._queue_fighter(cx, cy)
                # Desperate situation (badly damaged + swarmed): launch in pairs
                if hp_ratio < 0.4:
                    self._queue_fighter(cx, cy)
                self._deploy_timer = self.DEPLOY_INTERVAL * 0.4

            elif self._deploy_timer <= 0:
                self._queue_fighter(cx, cy)
                self._deploy_timer = self.DEPLOY_INTERVAL
        elif not enemy_detected and live_count < deploy_cap and self._deploy_timer <= 0:
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

        # Parked fighters on the flight deck — 3 rows of 5
        in_hangar = max(0, self.MAX_FIGHTERS - sum(1 for f in self._active_fighters if f.alive))
        if in_hangar > 0 and L > 10:
            fw    = max(2, int(L * 0.055))   # fighter half-length in screen px
            fh    = max(1, int(fw * 0.45))   # fighter half-width
            f_col = _FIGHTER_COLORS[self.team]
            COLS  = 5
            # Three deck rows (in local ly fractions of W)
            row_ly = (-0.065, 0.005, 0.075)
            x_min_f, x_max_f = -0.60, 0.65
            col_step = (x_max_f - x_min_f) / max(1, COLS - 1)
            drawn = 0
            for row_idx, ly_frac in enumerate(row_ly):
                for col_idx in range(COLS):
                    if drawn >= in_hangar:
                        break
                    slot_lx = (x_min_f + col_idx * col_step) * L
                    slot_ly = ly_frac * W
                    fsx = cx + slot_lx * cos_a - slot_ly * sin_a
                    fsy = cy + slot_lx * sin_a + slot_ly * cos_a
                    nose = (fsx + cos_a * fw,                      fsy + sin_a * fw)
                    wl   = (fsx - cos_a * fw * 0.55 + sin_a * fh,  fsy - sin_a * fw * 0.55 - cos_a * fh)
                    wr   = (fsx - cos_a * fw * 0.55 - sin_a * fh,  fsy - sin_a * fw * 0.55 + cos_a * fh)
                    pygame.draw.polygon(surface, f_col, [nose, wl, wr])
                    drawn += 1
                if drawn >= in_hangar:
                    break

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
        w = 110
        h = 40
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

        if self.hold_fire:
            self._has_target = False
            self._charge     = max(0.0, self._charge - dt * 0.5)
            return

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
