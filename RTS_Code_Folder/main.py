"""
main.py — Space Ranters: RTS fleet commander.

Main Menu  → choose Blue or Red team.
In-game    → command your fleet to destroy the enemy.

Both fleets start parked at opposite ends of the map and hold there (still
firing back if attacked) until ordered out: your ships deploy the moment you
give them an order, while the enemy fleet is commanded by an adaptive AI
that decides for itself when and how hard to commit (see commander.py).

Controls (in-game):
  LMB click        — select a friendly ship
  LMB drag         — box-select multiple ships
  Shift + LMB      — add / remove from selection
  RMB click        — move order (formation-aware, empty space)
  RMB click ally   — follow order (escort a friendly ship in formation)
  RMB click enemy  — attack order
  A + RMB click    — attack-move (advance, engage anything met en route)
  Shift + RMB      — queue the order instead of replacing the current one
  RMB drag         — pan camera
  Scroll wheel     — zoom in / out
  Ctrl+A           — select all your ships
  Ctrl + 1-9       — assign selected ships to control group
  1-9              — recall control group (Shift adds to selection)
  H                — hold position (stay put, keep firing)
  F                — toggle hold fire
  Escape           — deselect all / clear orders
"""

import sys
import math
import random
import threading
import pygame
from camera import Camera
from entities import (AICharacter, Laser, Explosion, Fighter, Carrier, Destroyer,
                      Star, Planet, Constructor, DysonSphere, DysonNode,
                      GlowingAsteroid, MineableAsteroid, MinerShip, CargoShip)
from commander import AICommander
from neural_commander import NeuralCommander

# ── Display ───────────────────────────────────────────────────────────────────
SCREEN_W, SCREEN_H = 1000, 800

# ── World ─────────────────────────────────────────────────────────────────────
map_scale_factor = 6
WORLD_W = 4000 * map_scale_factor
WORLD_H = 3200 * map_scale_factor

AICharacter.WORLD_W = WORLD_W
AICharacter.WORLD_H = WORLD_H

FPS      = 60
NUM_AI   = 100

ZOOM_MIN  = 0.10
ZOOM_MAX  = 4.0
ZOOM_STEP = 1.2

BG_DARK = (0, 0, 0)

# Team palette
TEAM_COLORS = [
    (60,  120, 255),   # 0 = Blue
    (255,  50,  50),   # 1 = Red
]
TEAM_NAMES = ["BLUE COMMAND", "RED COMMAND"]

# ── Resource / build system ───────────────────────────────────────────────────
# Planet  → material mapping (see MinerShip._PLANET_YIELDS / _ASTEROID_YIELDS)
# home    → Iron + Silicon + Copper
# rocky   → Iron + Nickel
# water   → Copper + Ice
# gas     → Fuel + Helium-3
# asteroid→ Titanium + Platinum  (finite, high rate)
# glowing → Crystal  + Uranium   (finite, high rate)

ALL_MATERIALS = [
    'iron', 'nickel', 'copper', 'silicon', 'ice',
    'helium3', 'fuel', 'titanium', 'platinum', 'crystal', 'uranium',
]

MATERIAL_ABBREV = {
    'iron':     'Fe',   'nickel':   'Ni',  'copper':  'Cu',  'silicon': 'Si',
    'ice':      'H₂O', 'helium3': 'He³', 'fuel': 'Fu',
    'titanium': 'Ti',   'platinum': 'Pt',  'crystal': 'Cr',  'uranium': 'U',
}

MATERIAL_COLOR = {
    'iron':     (180, 130,  80),
    'nickel':   (160, 160, 150),
    'copper':   (210, 140,  40),
    'silicon':  (100, 200, 100),
    'ice':      (160, 220, 255),
    'helium3':  (255, 160,  80),
    'fuel':     (220, 200,  70),
    'titanium': (150, 200, 230),
    'platinum': (220, 220, 200),
    'crystal':  (190, 100, 255),
    'uranium':  ( 80, 255, 100),
}

STARTING_MATERIALS = {
    'iron':   80,
    'nickel': 20,
    'copper': 25,
}

SHIP_COSTS = {
    'MinerShip':   {'iron': 10, 'nickel': 5},
    'CargoShip':   {'iron': 15, 'copper': 8},
    'AICharacter': {'iron': 30, 'copper': 12, 'silicon': 8},
    'Destroyer':   {'iron': 50, 'copper': 20, 'titanium': 15, 'fuel': 20},
    'Carrier':     {'iron': 80, 'copper': 30, 'titanium': 35,
                    'platinum': 10, 'crystal': 15, 'fuel': 45},
}

_BUILD_MENU_ROWS = [
    ('MinerShip',   'Miner',     SHIP_COSTS['MinerShip']),
    ('CargoShip',   'Cargo',     SHIP_COSTS['CargoShip']),
    ('AICharacter', 'Frigate',   SHIP_COSTS['AICharacter']),
    ('Destroyer',   'Destroyer', SHIP_COSTS['Destroyer']),
    ('Carrier',     'Carrier',   SHIP_COSTS['Carrier']),
]

# ── Cached fonts (initialised on first use after pygame.font.init) ────────────
_FONT_SM     = None
_FONT_MED    = None
_FONT_BANNER = None

def _fonts():
    global _FONT_SM, _FONT_MED, _FONT_BANNER
    if _FONT_SM is None:
        _FONT_SM     = pygame.font.SysFont("monospace", 14)
        _FONT_MED    = pygame.font.SysFont("monospace", 16)
        _FONT_BANNER = pygame.font.SysFont("impact", 22)
    return _FONT_SM, _FONT_MED, _FONT_BANNER

# ── Pre-allocated HUD surfaces (created once, reused every frame) ─────────────
_HUD_PANEL  = None   # status panel top-left
_HUD_MM     = None   # minimap
_HUD_HINTS  = None   # pre-rendered hint text surfaces (never change)

def _ensure_hud_surfaces():
    global _HUD_PANEL, _HUD_MM, _HUD_HINTS
    if _HUD_PANEL is not None:
        return
    font_sm, _, _ = _fonts()
    _HUD_PANEL = pygame.Surface((300, 14 + 16 * 18), pygame.SRCALPHA)
    _HUD_MM    = pygame.Surface((180, 120), pygame.SRCALPHA)
    hints = [
        "LMB: Select   Shift+LMB: Add/Remove",
        "Drag LMB: Box select   Ctrl+A: All",
        "RMB: Move/Follow/Attack   A+RMB: Attack-move",
        "Shift+RMB: Queue   Ctrl+1-9: Group   H: Hold   F: Hold fire   Tab: Toggle HUD",
    ]
    _HUD_HINTS = [font_sm.render(h, True, (80, 80, 100)) for h in hints]


# ── World background ──────────────────────────────────────────────────────────
def _tile_image(surf, image_path, world_w, world_h, state=None):
    import os
    path = os.path.join(os.path.dirname(__file__), image_path)
    try:
        tile   = pygame.image.load(path)
        tw, th = tile.get_size()
        cols   = max(1, (world_w + tw - 1) // tw)
        rows   = max(1, (world_h + th - 1) // th)
        total  = cols * rows
        done   = 0
        for ry in range(rows):
            for rx in range(cols):
                surf.blit(tile, (rx * tw, ry * th))
                done += 1
                if state is not None and done % max(1, total // 40) == 0:
                    state['progress'] = 0.05 + 0.50 * (done / total)
    except pygame.error:
        surf.fill(BG_DARK)


def build_world_surface(state=None):
    surf = pygame.Surface((WORLD_W, WORLD_H))
    surf.fill(BG_DARK)
    _tile_image(surf, "RTS Background 2.png", WORLD_W, WORLD_H, state)
    return surf


# ── Loading screen ────────────────────────────────────────────────────────────
def _draw_loading(screen, stars, elapsed, player_team, step_text, progress):
    sw, sh = screen.get_size()
    screen.fill((2, 4, 14))

    # Drifting stars (reuse same star format as menu)
    for s in stars:
        s[1] = (s[1] + s[3] * 0.0003) % 1.0
        bri  = int(s[2] * 200 + 55)
        r    = 1 if s[2] < 0.7 else 2
        pygame.draw.circle(screen, (bri, bri, bri),
                           (int(s[0] * sw), int(s[1] * sh)), r)

    team_col = TEAM_COLORS[player_team]

    font_title = pygame.font.SysFont("impact",    54)
    font_sub   = pygame.font.SysFont("monospace", 18)
    font_step  = pygame.font.SysFont("monospace", 15)

    # Title
    title = font_title.render("SPACE RANTERS", True, (200, 220, 255))
    screen.blit(title, title.get_rect(center=(sw // 2, sh // 3)))

    # "Deploying <team>…"
    sub = font_sub.render(f"Deploying {TEAM_NAMES[player_team]}…", True, team_col)
    screen.blit(sub, sub.get_rect(center=(sw // 2, sh // 3 + 65)))

    # Progress bar
    bar_w = int(sw * 0.58)
    bar_h = 20
    bar_x = sw // 2 - bar_w // 2
    bar_y = sh // 2 + 30
    pygame.draw.rect(screen, (15, 20, 35),   (bar_x, bar_y, bar_w, bar_h), border_radius=10)
    fill_w = max(0, int(bar_w * min(progress, 1.0)))
    if fill_w > 0:
        pygame.draw.rect(screen, team_col,   (bar_x, bar_y, fill_w, bar_h), border_radius=10)
    pygame.draw.rect(screen, (55, 65, 100),  (bar_x, bar_y, bar_w, bar_h), 2, border_radius=10)

    # Percentage
    pct = font_step.render(f"{int(progress * 100)}%", True, (160, 170, 200))
    screen.blit(pct, pct.get_rect(midright=(bar_x - 10, bar_y + bar_h // 2)))

    # Step label
    step_surf = font_step.render(step_text, True, (120, 130, 160))
    screen.blit(step_surf, step_surf.get_rect(center=(sw // 2, bar_y + bar_h + 18)))

    # Animated dots
    for i in range(3):
        alpha = max(0, 0.5 + 0.5 * math.sin(elapsed * 4.0 - i * 1.1))
        col   = tuple(min(255, int(c * alpha)) for c in team_col)
        pygame.draw.circle(screen, col, (sw // 2 - 18 + i * 18, bar_y - 22), 5)


def run_loading_screen(screen, clock, player_team):
    """Animate a loading screen while building world + entities in a thread."""
    state = {
        'progress':      0.0,
        'step':          'Initialising…',
        'world_surf':    None,
        'ai_characters': None,
        'asteroids':     [],
        'done':          False,
    }

    def _load():
        state['step']     = 'Building star map…'
        state['progress'] = 0.03
        state['world_surf'] = build_world_surface(state)   # updates progress 0.05→0.55

        state['step']     = 'Placing asteroid field…'
        state['progress'] = 0.58
        state['asteroids'] = _build_asteroid_field(
            state['world_surf'], WORLD_W, WORLD_H)

        state['step']     = 'Deploying fleets…'
        state['progress'] = 0.62
        result = setup_game()
        if isinstance(result, tuple):
            state['ai_characters'], state['solar_entities'] = result
        else:
            state['ai_characters'] = result
            state['solar_entities'] = []

        state['step']     = 'Forming battle groups…'
        state['progress'] = 0.92

        state['step']     = 'Ready for battle!'
        state['progress'] = 1.0
        state['done']     = True

    t = threading.Thread(target=_load, daemon=True)
    t.start()

    stars   = _make_menu_stars(160)
    elapsed = 0.0

    # Animate while loading
    while not state['done']:
        dt       = clock.tick(60) / 1000.0
        elapsed += dt
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit(); sys.exit()
        _draw_loading(screen, stars, elapsed, player_team,
                      state['step'], state['progress'])
        pygame.display.flip()

    # Hold "Ready!" for ~0.8 s so the player sees it
    hold = 0.0
    while hold < 0.8:
        dt       = clock.tick(60) / 1000.0
        elapsed += dt
        hold    += dt
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit(); sys.exit()
        _draw_loading(screen, stars, elapsed, player_team,
                      state['step'], state['progress'])
        pygame.display.flip()

    t.join()
    return state['world_surf'], state['ai_characters'], state['solar_entities'], state['asteroids']


# ── Menu ──────────────────────────────────────────────────────────────────────
def _make_menu_stars(n=220):
    return [[random.uniform(0, 1), random.uniform(0, 1),
             random.uniform(0.4, 1.0), random.uniform(0.02, 0.06)]
            for _ in range(n)]


def _draw_menu(screen, stars, elapsed, hovered):
    sw, sh = screen.get_size()
    screen.fill((2, 4, 14))

    # Drifting stars
    for s in stars:
        s[1] = (s[1] + s[3] * 0.0003) % 1.0
        sx = int(s[0] * sw)
        sy = int(s[1] * sh)
        bright = int(s[2] * 200 + 55)
        r = 1 if s[2] < 0.7 else 2
        pygame.draw.circle(screen, (bright, bright, bright), (sx, sy), r)

    font_title = pygame.font.SysFont("impact", 72)
    font_sub   = pygame.font.SysFont("monospace", 22)
    font_btn   = pygame.font.SysFont("impact", 32)
    font_hint  = pygame.font.SysFont("monospace", 14)

    # Title with glow layers
    title_text = "SPACE RANTERS"
    glow_col = (20, 60, 140)
    for offset in range(4, 0, -1):
        glow = font_title.render(title_text, True, glow_col)
        screen.blit(glow, glow.get_rect(center=(sw // 2 + offset, sh // 3 + offset)))
        screen.blit(glow, glow.get_rect(center=(sw // 2 - offset, sh // 3 + offset)))
    title_surf = font_title.render(title_text, True, (200, 220, 255))
    screen.blit(title_surf, title_surf.get_rect(center=(sw // 2, sh // 3)))

    sub = font_sub.render("Choose Your Fleet", True, (120, 140, 180))
    screen.blit(sub, sub.get_rect(center=(sw // 2, sh // 3 + 80)))

    # Team buttons
    btn_w, btn_h = 280, 90
    gap = 40
    total = btn_w * 2 + gap
    bx0 = sw // 2 - total // 2
    by  = sh // 2 + 10

    btn_rects = [
        pygame.Rect(bx0,           by, btn_w, btn_h),
        pygame.Rect(bx0 + btn_w + gap, by, btn_w, btn_h),
    ]

    dark_cols  = [(8, 18, 55),  (55, 8, 8)]
    rim_cols   = [(40, 100, 220), (220, 40, 40)]
    hover_cols = [(20, 50, 130), (130, 20, 20)]
    text_cols  = [(100, 180, 255), (255, 100, 100)]

    pulse = 0.5 + 0.5 * math.sin(elapsed * 3.0)

    for i, (rect, name) in enumerate(zip(btn_rects, TEAM_NAMES)):
        is_hov = (hovered == i)
        bg = hover_cols[i] if is_hov else dark_cols[i]
        rim = rim_cols[i]
        pygame.draw.rect(screen, bg,  rect, border_radius=12)
        rim_bright = tuple(min(255, int(c * (0.7 + 0.3 * pulse))) for c in rim) if is_hov else rim
        pygame.draw.rect(screen, rim_bright, rect, 3, border_radius=12)

        lbl = font_btn.render(name, True, text_cols[i])
        screen.blit(lbl, lbl.get_rect(center=rect.center))

    # Controls-layout button
    ctrl_w, ctrl_h = 280, 46
    ctrl_rect = pygame.Rect(sw // 2 - ctrl_w // 2, by + btn_h + 40, ctrl_w, ctrl_h)
    is_ctrl_hov = (hovered == 'controls')
    ctrl_bg  = (30, 35, 55) if is_ctrl_hov else (14, 16, 28)
    ctrl_rim = (130, 150, 200) if is_ctrl_hov else (70, 80, 110)
    pygame.draw.rect(screen, ctrl_bg,  ctrl_rect, border_radius=10)
    pygame.draw.rect(screen, ctrl_rim, ctrl_rect, 2, border_radius=10)
    font_ctrl = pygame.font.SysFont("monospace", 18, bold=True)
    ctrl_lbl  = font_ctrl.render("VIEW CONTROL LAYOUT", True, (190, 200, 225))
    screen.blit(ctrl_lbl, ctrl_lbl.get_rect(center=ctrl_rect.center))

    # Quit hint
    hint = font_hint.render("ESC — Quit", True, (60, 60, 80))
    screen.blit(hint, hint.get_rect(center=(sw // 2, ctrl_rect.bottom + 24)))

    return btn_rects, ctrl_rect


CONTROLS_TEXT = [
    ("LMB click",    "select a friendly ship"),
    ("LMB drag",     "box-select multiple ships"),
    ("Shift + LMB",  "add / remove from selection"),
    ("RMB click",    "move order (formation-aware, empty space)"),
    ("RMB on ally",  "follow order (escort that ship in formation)"),
    ("RMB on enemy", "attack order"),
    ("A + RMB",      "attack-move (advance, engage anything met en route)"),
    ("Shift + RMB",  "queue the order instead of replacing it"),
    ("RMB drag",     "pan camera"),
    ("Scroll wheel", "zoom in / out"),
    ("Ctrl+A",       "select all your ships"),
    ("Ctrl + 1-9",   "assign selected ships to a control group"),
    ("1-9",          "recall control group (Shift adds to selection)"),
    ("H",            "hold position — stay put, keep firing"),
    ("F",            "toggle hold fire"),
    ("Escape",       "deselect all / clear orders"),
]


def _draw_controls_overlay(screen, stars, elapsed):
    sw, sh = screen.get_size()
    screen.fill((2, 4, 14))

    for s in stars:
        s[1] = (s[1] + s[3] * 0.0003) % 1.0
        sx = int(s[0] * sw)
        sy = int(s[1] * sh)
        bright = int(s[2] * 200 + 55)
        r = 1 if s[2] < 0.7 else 2
        pygame.draw.circle(screen, (bright, bright, bright), (sx, sy), r)

    font_title = pygame.font.SysFont("impact", 36)
    font_key   = pygame.font.SysFont("monospace", 15, bold=True)
    font_desc  = pygame.font.SysFont("monospace", 15)
    font_hint  = pygame.font.SysFont("monospace", 13)

    title = font_title.render("CONTROL LAYOUT", True, (200, 220, 255))
    screen.blit(title, title.get_rect(center=(sw // 2, 36)))

    row_h   = max(22, min(28, (sh - 110) // len(CONTROLS_TEXT)))
    panel_w = min(760, sw - 60)
    panel_h = len(CONTROLS_TEXT) * row_h + 20
    panel_x = sw // 2 - panel_w // 2
    panel_y = 64

    panel = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
    panel.fill((10, 14, 28, 200))
    pygame.draw.rect(panel, (70, 80, 110), (0, 0, panel_w, panel_h), 2, border_radius=10)

    key_col_w = 170
    for i, (key, desc) in enumerate(CONTROLS_TEXT):
        y = 10 + i * row_h
        key_surf  = font_key.render(key, True, (120, 200, 255))
        desc_surf = font_desc.render(desc, True, (200, 205, 220))
        panel.blit(key_surf,  (20, y))
        panel.blit(desc_surf, (key_col_w, y))

    screen.blit(panel, (panel_x, panel_y))

    hint = font_hint.render("Click anywhere or press ESC to return", True, (120, 130, 160))
    screen.blit(hint, hint.get_rect(center=(sw // 2, min(sh - 16, panel_y + panel_h + 22))))


def run_menu(screen, clock):
    """Show the main menu; return chosen team index (0=blue, 1=red)."""
    stars   = _make_menu_stars()
    elapsed = 0.0
    showing_controls = False
    while True:
        dt = clock.tick(60) / 1000.0
        elapsed += dt
        mx, my = pygame.mouse.get_pos()

        if showing_controls:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    pygame.quit(); sys.exit()
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    showing_controls = False
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    showing_controls = False
            _draw_controls_overlay(screen, stars, elapsed)
            pygame.display.flip()
            continue

        hovered = None
        clicked_ctrl = False
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit(); sys.exit()
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                pygame.quit(); sys.exit()
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                btn_rects, ctrl_rect = _draw_menu(screen, stars, elapsed, hovered)
                for i, rect in enumerate(btn_rects):
                    if rect.collidepoint(event.pos):
                        return i   # 0 = blue, 1 = red
                if ctrl_rect.collidepoint(event.pos):
                    clicked_ctrl = True

        if clicked_ctrl:
            showing_controls = True
            continue

        btn_rects, ctrl_rect = _draw_menu(screen, stars, elapsed, hovered)
        for i, rect in enumerate(btn_rects):
            if rect.collidepoint((mx, my)):
                hovered = i
        if ctrl_rect.collidepoint((mx, my)):
            hovered = 'controls'

        pygame.display.flip()


# ── Game setup ────────────────────────────────────────────────────────────────
SPAWN_SIDE_FRAC = 0.15   # team 0 spawns this far from the left edge, team 1 from the right


def _team_spawn_center(team):
    """Fixed spawn anchor for a team — team 0 always starts on the west side
    of the map, team 1 always on the east side, regardless of which one the
    player picked, so the two fleets always open on opposite sides."""
    frac = SPAWN_SIDE_FRAC if team == 0 else 1.0 - SPAWN_SIDE_FRAC
    return (WORLD_W * frac, WORLD_H * 0.5)


SYSTEM_PATROL_RADIUS = 5500.0   # idle fleets patrol within this distance of their home star


def _make_waypoints(team=None):
    if team is None:
        return [(random.randint(200, WORLD_W - 200),
                 random.randint(200, WORLD_H - 200)) for _ in range(5)]
    # Idle ships have no task yet — keep their patrol loop inside the home
    # solar system instead of wandering across the whole map.
    star_x, star_y = _team_star_position(team)

    def _point_in_system():
        angle  = random.uniform(0, math.tau)
        radius = random.uniform(0, SYSTEM_PATROL_RADIUS)
        return (max(200, min(WORLD_W - 200, star_x + math.cos(angle) * radius)),
                max(200, min(WORLD_H - 200, star_y + math.sin(angle) * radius)))

    return [_point_in_system() for _ in range(5)]


def _team_star_position(team):
    if team == 0:
        return (6000, 6000)  # Top-left corner
    else:
        return (18000, 13200)  # Bottom-right corner


def _build_solar_system(team):
    star_x, star_y = _team_star_position(team)
    star = Star(star_x, star_y, radius=578, color=TEAM_COLORS[team])
    planet_types = ['home', 'rocky', 'water', 'gas', 'rocky', 'water', 'gas']
    orbit_radii = [1350, 1950, 2550, 3150, 3750, 4350, 4950]
    planets = []
    for i, planet_type in enumerate(planet_types):
        angle = random.uniform(0, math.tau)
        speed = 0.020 - i * 0.0025  # innermost fastest, outermost slowest
        radius = 215 if planet_type == 'rocky' else 248 if planet_type == 'water' else 330
        if planet_type == 'home':
            radius = 297
        planets.append(
            Planet(star_x, star_y, orbit_radii[i], angle, speed,
                   planet_type, team, radius)
        )
    home_planet = next(p for p in planets if p.planet_type == 'home')
    constructor = Constructor(home_planet, team=team)

    dyson_sphere = DysonSphere(star_x, star_y, star_radius=578, team=team)
    dyson_orbit = dyson_sphere.orbit_radius
    dyson_nodes = [
        DysonNode(star_x, star_y, orbit_radius=dyson_orbit,
                  angle=i * math.tau / 4, orbit_speed=0.032,
                  team=team, node_index=i)
        for i in range(4)
    ]

    return [star, dyson_sphere] + dyson_nodes + planets + [constructor]


_ASTEROID_TOTAL   = 320   # total rocks in the diagonal field
_ASTEROID_GLOW_NTH =  25   # every Nth rock is a live glowing entity; rest baked into bg

_ASTEROID_MINEABLE_N = 12   # number of large interactable asteroid entities

_SHIP_SEP_DIST  = 180.0   # world units — all ships push apart when closer than this
_SHIP_SEP_FORCE = 150.0   # separation push strength (applied as position nudge for eco ships, velocity for combat)

# Respawn: when alive counts fall below these, new asteroids are spawned
_RESPAWN_MIN_ORE   = 4   # minimum live MineableAsteroids before new ones appear
_RESPAWN_MIN_GLOW  = 2   # minimum live GlowingAsteroids before new ones appear


def _build_asteroid_field(world_surf: pygame.Surface,
                          world_w: float, world_h: float) -> list:
    """
    Scatter _ASTEROID_TOTAL rocks along the top-right→bottom-left diagonal band.
    Non-glowing rocks are painted directly onto world_surf as static background art.
    Returns a list containing GlowingAsteroid and MineableAsteroid entities.
    """
    glowing = []
    diag     = math.sqrt(world_w ** 2 + world_h ** 2)
    # Unit vector perpendicular to the diagonal axis (rotated 90°)
    perp_x   =  world_h / diag
    perp_y   =  world_w / diag
    band_half = 600.0   # narrow corridor so asteroids form a line, not a cloud

    for i in range(_ASTEROID_TOTAL):
        t  = random.uniform(0.0, 1.0)   # evenly spread along the full diagonal
        bx = world_w * (1.0 - t)
        by = world_h * t
        off = random.uniform(-band_half, band_half)
        wx  = max(0.0, min(world_w, bx + off * perp_x))
        wy  = max(0.0, min(world_h, by + off * perp_y))

        if i % _ASTEROID_GLOW_NTH == 0:
            glowing.append(GlowingAsteroid(wx, wy))
        else:
            # Paint a static rock polygon directly onto the world surface
            radius = random.randint(22, 75)
            n      = random.randint(6, 10)
            a0     = random.uniform(0.0, math.tau)
            pts    = [
                (int(wx + math.cos(a0 + j * math.tau / n + random.uniform(-0.3, 0.3))
                     * radius * random.uniform(0.55, 1.0)),
                 int(wy + math.sin(a0 + j * math.tau / n + random.uniform(-0.3, 0.3))
                     * radius * random.uniform(0.55, 1.0)))
                for j in range(n)
            ]
            pygame.draw.polygon(world_surf, (168, 162, 155), pts)
            pygame.draw.polygon(world_surf, (210, 205, 200), pts, 1)

    # Scatter large interactable MineableAsteroid entities along the same band
    mineable = []
    for _ in range(_ASTEROID_MINEABLE_N):
        t   = random.uniform(0.05, 0.95)
        bx  = world_w * (1.0 - t)
        by  = world_h * t
        off = random.uniform(-band_half * 0.8, band_half * 0.8)
        mx  = max(0.0, min(world_w, bx + off * perp_x))
        my  = max(0.0, min(world_h, by + off * perp_y))
        mineable.append(MineableAsteroid(mx, my))

    return glowing + mineable


def setup_game():  # both sides start with resources only, no pre-built ships
    solar_entities = []
    for team in (0, 1):
        solar_entities.extend(_build_solar_system(team))
    ai_characters = []

    return ai_characters, solar_entities


# ── Team strategy (fleet-level "commander" layer) ───────────────────────────
def update_team_strategy(ai_characters):
    """Recompute per-team aggregate stats once a frame and publish them onto
    AICharacter as shared class state, so every ship's update_combat can read
    them cheaply instead of each ship re-scanning the whole fleet."""
    team_hp = {0: 0.0, 1: 0.0}
    fleets:  dict = {}   # id(leader) -> [leader, total_hp]
    for s in ai_characters:
        if not s.alive:
            continue
        team_hp[s.team] += s.hp
        leader = s.fleet_leader
        if leader is not None and leader.alive:
            entry = fleets.setdefault(id(leader), [leader, 0.0])
            entry[1] += s.hp

    AICharacter.team_strength_ratio = {
        0: team_hp[0] / max(1.0, team_hp[1]),
        1: team_hp[1] / max(1.0, team_hp[0]),
    }

    focus = {0: None, 1: None}
    for team in (0, 1):
        enemy_team = 1 - team
        candidates = [v for v in fleets.values() if v[0].team == enemy_team]
        if candidates:
            weakest = min(candidates, key=lambda v: v[1])
            focus[team] = weakest[0]
    AICharacter.team_focus_fleet = focus


# ── RTS helpers ───────────────────────────────────────────────────────────────
def _ship_screen_radius(ship, camera):
    return max(8, int(math.hypot(ship.width, ship.height) / 2 * camera.zoom))


def get_ship_at(ships, camera, sx, sy):
    """Return the ship (if any) whose hull is closest to screen position."""
    best_ship = None
    best_dist = float('inf')
    for ship in ships:
        if not ship.alive:
            continue
        wx, wy = camera.world_to_screen(
            ship.wx + ship.width  / 2,
            ship.wy + ship.height / 2,
        )
        r    = _ship_screen_radius(ship, camera)
        dist = math.hypot(sx - wx, sy - wy)
        if dist < r and dist < best_dist:
            best_dist = dist
            best_ship = ship
    return best_ship


def get_ships_in_box(ships, camera, box_rect):
    result = []
    for ship in ships:
        if not ship.alive:
            continue
        sx, sy = camera.world_to_screen(
            ship.wx + ship.width  / 2,
            ship.wy + ship.height / 2,
        )
        if box_rect.collidepoint(sx, sy):
            result.append(ship)
    return result


def draw_selection_ring(surface, camera, ship, elapsed, player_team):
    sx, sy = camera.world_to_screen(
        ship.wx + ship.width  / 2,
        ship.wy + ship.height / 2,
    )
    r     = _ship_screen_radius(ship, camera) + 5
    pulse = 0.6 + 0.4 * math.sin(elapsed * 4.0)
    col   = tuple(min(255, int(c * pulse)) for c in TEAM_COLORS[player_team])
    pygame.draw.circle(surface, col, (sx, sy), r, 2)
    pygame.draw.circle(surface, (*col, 60), (sx, sy), r + 3, 1)


def draw_command_marker(surface, camera, wx, wy, elapsed, color):
    sx, sy = camera.world_to_screen(wx, wy)
    pulse  = 0.5 + 0.5 * math.sin(elapsed * 6.0)
    r      = int(10 + 4 * pulse)
    # Cross / X marker
    for dx, dy in [(-r, 0), (r, 0), (0, -r), (0, r)]:
        pygame.draw.line(surface, color, (sx, sy), (sx + dx, sy + dy), 2)
    pygame.draw.circle(surface, color, (sx, sy), 4)


_SELECT_BOX_FILL = None  # reusable tinted fill surface, grown as needed

def draw_select_box(surface, start, end):
    global _SELECT_BOX_FILL
    if start is None:
        return
    x0, y0 = start
    x1, y1 = end
    bx, by = min(x0, x1), min(y0, y1)
    bw, bh = abs(x1 - x0), abs(y1 - y0)
    if bw < 2 or bh < 2:
        return
    # Grow the cached fill surface only when the box is larger than ever before
    if _SELECT_BOX_FILL is None or _SELECT_BOX_FILL.get_width() < bw or _SELECT_BOX_FILL.get_height() < bh:
        nw = max(bw, _SELECT_BOX_FILL.get_width()  if _SELECT_BOX_FILL else 0)
        nh = max(bh, _SELECT_BOX_FILL.get_height() if _SELECT_BOX_FILL else 0)
        _SELECT_BOX_FILL = pygame.Surface((nw, nh), pygame.SRCALPHA)
        _SELECT_BOX_FILL.fill((80, 160, 255, 25))
    surface.blit(_SELECT_BOX_FILL, (bx, by), (0, 0, bw, bh))
    pygame.draw.rect(surface, (80, 160, 255, 180), (bx, by, bw, bh), 1)


# ── HUD ───────────────────────────────────────────────────────────────────────
# Per-session cached renders that only rebuild when their inputs change.
_hud_banner_surf  = None   # rendered banner Surface
_hud_banner_bg    = None   # solid-bg Surface for banner
_hud_minimap_lbl  = None   # "MINIMAP" label Surface
_hud_detail_bg    = None   # reusable bg strip for ship detail


def draw_hud(screen, camera, ai_characters, player_team, selected_ships,
             fps, screen_w, screen_h, player_orders,
             team_materials=None):
    global _hud_banner_surf, _hud_banner_bg, _hud_minimap_lbl, _hud_detail_bg

    _ensure_hud_surfaces()
    font_sm, font_med, font_banner = _fonts()

    team_col   = TEAM_COLORS[player_team]
    enemy_team = 1 - player_team

    f_count = e_count = f_carr = e_carr = 0
    for s in ai_characters:
        if not s.alive:
            continue
        if s.team == player_team:
            f_count += 1
            if isinstance(s, Carrier):
                f_carr += 1
        else:
            e_count += 1
            if isinstance(s, Carrier):
                e_carr += 1

    # ── Top-left status panel (reuse pre-allocated Surface) ───────────────────
    panel   = _HUD_PANEL
    panel_h = panel.get_height()
    panel.fill((0, 0, 0, 155))
    pygame.draw.rect(panel, (*team_col, 200), (0, 0, 4, panel_h))

    mat = team_materials.get(player_team, {}) if team_materials else {}

    # FPS
    panel.blit(font_sm.render(f"FPS: {fps:.0f}", True, (160, 160, 180)), (10, 7))

    # Materials in two columns: left col x=10, right col x=150
    _MAT_ROWS = [
        ('iron',     'nickel'),
        ('copper',   'silicon'),
        ('ice',      'helium3'),
        ('fuel',     'titanium'),
        ('platinum', 'crystal'),
        ('uranium',  None),
    ]
    y = 25
    for left, right in _MAT_ROWS:
        for ci, mn in enumerate([left, right]):
            if mn is None:
                continue
            v   = int(mat.get(mn, 0))
            txt = f"{MATERIAL_ABBREV.get(mn, mn)}:{v}"
            col = MATERIAL_COLOR.get(mn, (180, 180, 180))
            panel.blit(font_sm.render(txt, True, col), (10 + ci * 140, y))
        y += 18

    # Fleet / selection info
    y += 4
    for line, col in [
        (f"YOUR FLEET:  {f_count:3d} ({f_carr} carriers)", team_col),
        (f"ENEMY FLEET: {e_count:3d} ({e_carr} carriers)", TEAM_COLORS[enemy_team]),
        ("", (0, 0, 0)),
        (f"SELECTED: {len(selected_ships)} ship{'s' if len(selected_ships) != 1 else ''}",
         (220, 220, 100) if selected_ships else (160, 160, 180)),
        (f"ORDERS ACTIVE: {len(player_orders)}", (160, 160, 180)),
    ]:
        if line:
            panel.blit(font_sm.render(line, True, col), (10, y))
        y += 18

    screen.blit(panel, (8, 8))

    # ── Selected ship detail (bottom centre) ──────────────────────────────────
    if selected_ships:
        types = {}
        for s in selected_ships:
            t = type(s).__name__
            types[t] = types.get(t, 0) + 1
        type_str = "  ".join(f"{v}× {k}" for k, v in types.items())
        if selected_ships and all(getattr(s, 'player_hold', False) for s in selected_ships):
            type_str += "   [HOLDING]"
        if selected_ships and all(getattr(s, 'hold_fire', False) for s in selected_ships):
            type_str += "   [HOLD FIRE]"

        # ── Miner resource info ───────────────────────────────────────────────
        def _entity_res_str(entity):
            """Return (abbrev_string, color) describing what an entity yields."""
            ylds = getattr(entity, 'yields', {})
            mats = list(ylds.keys())
            if not mats:
                return getattr(entity, 'planet_type', '?').title(), (180, 180, 180)
            name = '+'.join(MATERIAL_ABBREV.get(m, m.title()) for m in mats[:2])
            col  = MATERIAL_COLOR.get(mats[0], (200, 200, 200))
            return name, col

        miners_sel = [s for s in selected_ships if type(s).__name__ == 'MinerShip']
        miner_info_surfs = []
        if miners_sel:
            if len(miners_sel) == 1:
                m = miners_sel[0]
                if m.state == 'landed' and m._landed_planet is not None:
                    res_name, col = _entity_res_str(m._landed_planet)
                    ptype = getattr(m._landed_planet, 'planet_type', '')
                    miner_info_surfs.append((font_sm.render(f"Mining: {res_name}  ({ptype})", True, col), col))
                elif m.state == 'to_planet' and m._target is not None:
                    res_name, col = _entity_res_str(m._target)
                    col = tuple(max(0, c - 40) for c in col)
                    miner_info_surfs.append((font_sm.render(f"En route → {res_name}", True, col), col))
                else:
                    miner_info_surfs.append((font_sm.render("Idle", True, (140, 140, 140)), (140, 140, 140)))
            else:
                counts: dict = {}
                idle = 0
                for m in miners_sel:
                    entity = m._landed_planet if m.state == 'landed' else (
                             m._target if m.state == 'to_planet' else None)
                    if entity is not None:
                        res_name, _ = _entity_res_str(entity)
                        counts[res_name] = counts.get(res_name, 0) + 1
                    else:
                        idle += 1
                parts = [f"{n}×{r}" for r, n in counts.items()]
                if idle:
                    parts.append(f"{idle}×idle")
                col = (180, 180, 180)
                miner_info_surfs.append((font_sm.render("Mining: " + "  ".join(parts), True, col), col))

        # Draw: type line then optional miner line
        has_miner_line = bool(miner_info_surfs)
        base_y  = screen_h - (68 if has_miner_line else 46)
        detail  = font_med.render(type_str, True, (220, 220, 100))
        dw      = detail.get_width()
        mw      = max((s.get_width() for s, _ in miner_info_surfs), default=0)
        bg_w    = max(dw, mw) + 20
        bg_h    = 28 + (20 if has_miner_line else 0)
        dx      = screen_w // 2 - bg_w // 2
        old_sz = _hud_detail_bg.get_size() if _hud_detail_bg else (0, 0)
        if _hud_detail_bg is None or old_sz[0] < bg_w or old_sz[1] < bg_h:
            _hud_detail_bg = pygame.Surface((bg_w, bg_h), pygame.SRCALPHA)
        _hud_detail_bg.fill((0, 0, 0, 160))
        screen.blit(_hud_detail_bg, (dx, base_y))
        screen.blit(detail, (screen_w // 2 - dw // 2, base_y + 4))
        for i, (surf, _) in enumerate(miner_info_surfs):
            screen.blit(surf, (screen_w // 2 - surf.get_width() // 2, base_y + 26 + i * 18))

    # ── Controls hints (pre-rendered, static) ─────────────────────────────────
    hint_y = screen_h - len(_HUD_HINTS) * 16 - 8
    for i, surf in enumerate(_HUD_HINTS):
        screen.blit(surf, (8, hint_y + i * 16))

    # ── Minimap (reuse pre-allocated Surface) ─────────────────────────────────
    mm_w, mm_h = 180, 120
    mm_x = screen_w - mm_w - 10
    mm_y = 10
    mm   = _HUD_MM
    mm.fill((0, 0, 0, 170))
    pygame.draw.rect(mm, (50, 50, 70), (0, 0, mm_w, mm_h), 1)

    mm_sx = mm_w / WORLD_W
    mm_sy = mm_h / WORLD_H
    sel_ids = {id(s) for s in selected_ships}
    t0_col  = TEAM_COLORS[0]
    t1_col  = TEAM_COLORS[1]
    t0_dim  = (t0_col[0] >> 1, t0_col[1] >> 1, t0_col[2] >> 1)
    t1_dim  = (t1_col[0] >> 1, t1_col[1] >> 1, t1_col[2] >> 1)
    for ship in ai_characters:
        if not ship.alive:
            continue
        mx2 = int((ship.wx + ship.width  * 0.5) * mm_sx)
        my2 = int((ship.wy + ship.height * 0.5) * mm_sy)
        if id(ship) in sel_ids:
            col = (255, 255, 100)
        elif ship.team == player_team:
            col = t0_col if player_team == 0 else t1_col
        else:
            col = t0_dim if player_team != 0 else t1_dim
        pygame.draw.circle(mm, col, (mx2, my2), 3 if isinstance(ship, Carrier) else 1)

    vp_x  = int(camera.x * mm_sx)
    vp_y  = int(camera.y * mm_sy)
    vp_w2 = max(1, int(camera.screen_width  / camera.zoom * mm_sx))
    vp_h2 = max(1, int(camera.screen_height / camera.zoom * mm_sy))
    pygame.draw.rect(mm, (120, 120, 160), (vp_x, vp_y, vp_w2, vp_h2), 1)
    screen.blit(mm, (mm_x, mm_y))

    if _hud_minimap_lbl is None:
        _hud_minimap_lbl = font_sm.render("MINIMAP", True, (80, 80, 110))
    screen.blit(_hud_minimap_lbl, (mm_x + 4, mm_y + mm_h + 2))

    # ── Team banner (cached, never changes mid-game) ───────────────────────────
    if _hud_banner_surf is None:
        banner_text      = f"{TEAM_NAMES[player_team]}  vs  {TEAM_NAMES[enemy_team]}"
        _hud_banner_surf = font_banner.render(banner_text, True, team_col)
        bw               = _hud_banner_surf.get_width() + 20
        _hud_banner_bg   = pygame.Surface((bw, 30), pygame.SRCALPHA)
        _hud_banner_bg.fill((0, 0, 0, 140))
    bx = screen_w // 2 - _hud_banner_surf.get_width() // 2
    screen.blit(_hud_banner_bg,  (bx - 10, 8))
    screen.blit(_hud_banner_surf, (bx, 12))


# ── Planet info panel ────────────────────────────────────────────────────────

def draw_planet_info(screen, planet, screen_w):
    """Draw a small panel showing the selected planet's type and harvestable materials."""
    font_sm, font_med, _ = _fonts()
    ylds      = getattr(planet, 'yields', {})
    materials = list(ylds.keys())

    panel_w = 210
    row_h   = 20
    panel_h = 10 + 24 + 16 + len(materials) * row_h + 8

    px = screen_w - panel_w - 10
    py = 152  # below minimap (10 + 120 + label)

    surf = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
    surf.fill((0, 0, 0, 185))
    pygame.draw.rect(surf, (80, 80, 110), (0, 0, panel_w, panel_h), 1)

    type_label = 'Home Planet' if planet.planet_type == 'home' else planet.planet_type.title() + ' Planet'
    surf.blit(font_med.render(type_label, True, (220, 220, 255)), (8, 6))

    y = 32
    surf.blit(font_sm.render('Materials:', True, (160, 160, 180)), (8, y))
    y += 18

    for mat in materials:
        col    = MATERIAL_COLOR.get(mat, (200, 200, 200))
        abbrev = MATERIAL_ABBREV.get(mat, mat.title())
        rate   = ylds[mat]
        pygame.draw.circle(surf, col, (14, y + 7), 5)
        surf.blit(font_sm.render(f'{abbrev}  {mat.title()}  {rate}/s', True, col), (26, y))
        y += row_h

    screen.blit(surf, (px, py))


def draw_asteroid_info(screen, asteroid, screen_w):
    """Draw a small panel showing the selected asteroid's materials and remaining resources."""
    font_sm, font_med, _ = _fonts()
    ylds      = getattr(asteroid, 'yields', {})
    materials = list(ylds.keys())
    res_frac  = max(0.0, asteroid.resources / asteroid.max_resources) if asteroid.max_resources else 0.0

    panel_w = 210
    row_h   = 20
    panel_h = 10 + 24 + 16 + len(materials) * row_h + 26 + 8

    px = screen_w - panel_w - 10
    py = 152

    surf = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
    surf.fill((0, 0, 0, 185))
    pygame.draw.rect(surf, (80, 80, 110), (0, 0, panel_w, panel_h), 1)

    type_label = 'Glowing Asteroid' if asteroid.planet_type == 'glowing' else 'Asteroid'
    surf.blit(font_med.render(type_label, True, (220, 220, 255)), (8, 6))

    y = 32
    surf.blit(font_sm.render('Materials:', True, (160, 160, 180)), (8, y))
    y += 18

    for mat in materials:
        col    = MATERIAL_COLOR.get(mat, (200, 200, 200))
        abbrev = MATERIAL_ABBREV.get(mat, mat.title())
        rate   = ylds[mat]
        pygame.draw.circle(surf, col, (14, y + 7), 5)
        surf.blit(font_sm.render(f'{abbrev}  {mat.title()}  {rate}/s', True, col), (26, y))
        y += row_h

    y += 4
    bar_w  = panel_w - 16
    bar_h  = 6
    fill_w = max(0, int(bar_w * res_frac))
    pygame.draw.rect(surf, (40, 30, 50), (8, y, bar_w, bar_h))
    bar_col = (190, 100, 255) if asteroid.planet_type == 'glowing' else (200, 160, 60)
    pygame.draw.rect(surf, bar_col, (8, y, fill_w, bar_h))
    surf.blit(font_sm.render(f'{int(res_frac * 100)}% remaining', True, (150, 150, 170)), (8, y + 9))

    screen.blit(surf, (px, py))


# ── Quit confirmation ────────────────────────────────────────────────────────
def _quit_confirm_rects(screen):
    sw, sh = screen.get_size()
    btn_w, btn_h = 170, 56
    bx0 = sw // 2 - btn_w // 2
    by  = sh // 2 + 40
    return pygame.Rect(bx0, by, btn_w, btn_h)


def _draw_quit_confirm(screen, elapsed, mouse_pos):
    """Dim + freeze the battle behind a paused 'closing the window' notice.
    Returns resume_rect for click hit-testing."""
    sw, sh = screen.get_size()
    overlay = pygame.Surface((sw, sh), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 170))
    screen.blit(overlay, (0, 0))

    font_title = pygame.font.SysFont("impact", 36)
    font_sub   = pygame.font.SysFont("monospace", 15)
    font_btn   = pygame.font.SysFont("impact", 26)

    title = font_title.render("GAME PAUSED", True, (230, 230, 240))
    screen.blit(title, title.get_rect(center=(sw // 2, sh // 2 - 60)))

    sub = font_sub.render("Close the window again (titlebar X) to quit to desktop.",
                           True, (160, 160, 180))
    screen.blit(sub, sub.get_rect(center=(sw // 2, sh // 2 - 18)))

    resume_rect = _quit_confirm_rects(screen)
    hov_resume  = resume_rect.collidepoint(mouse_pos)
    pulse       = 0.6 + 0.4 * math.sin(elapsed * 4.0)

    bg_resume  = (35, 45, 70) if hov_resume else (16, 20, 32)
    rim_resume = tuple(min(255, int(c * pulse))
                        for c in ((150, 180, 230) if hov_resume else (70, 80, 110)))
    pygame.draw.rect(screen, bg_resume,  resume_rect, border_radius=10)
    pygame.draw.rect(screen, rim_resume, resume_rect, 3, border_radius=10)
    lbl_resume = font_btn.render("RESUME", True, (215, 222, 235))
    screen.blit(lbl_resume, lbl_resume.get_rect(center=resume_rect.center))

    hint = font_sub.render("Esc / click RESUME to keep playing", True, (110, 115, 135))
    screen.blit(hint, hint.get_rect(center=(sw // 2, resume_rect.bottom + 30)))

    return resume_rect


# ── Resource / build helpers ──────────────────────────────────────────────────

def _ai_assign_miners(team, miners, asteroids, planets_by_team):
    """Send idle miners to best targets: richest asteroids first, then home planets.
    Spreads miners across targets instead of piling onto one."""
    idle = [m for m in miners if m.team == team and m.alive and m.state == 'idle']
    if not idle:
        return

    # Count how many miners are already committed to each target
    load: dict = {}
    for m in miners:
        if m.team == team and m.alive and m.state in ('to_planet', 'landed'):
            tgt = getattr(m, '_landed_planet', None)
            if tgt is not None:
                load[id(tgt)] = load.get(id(tgt), 0) + 1

    rich_asts  = sorted(
        [a for a in asteroids if hasattr(a, 'resources') and a.resources > 30],
        key=lambda a: a.resources, reverse=True,
    )
    own_planets = list(planets_by_team.get(team, []))
    candidates  = rich_asts + own_planets
    if not candidates:
        return

    for m in idle:
        best = min(candidates, key=lambda t: load.get(id(t), 0))
        m.send_to(best)
        load[id(best)] = load.get(id(best), 0) + 1


def _ai_queue_build(team, constructors_by_team, miners, cargo_ships,
                    team_materials, asteroids=None, planets_by_team=None):
    """Queue the best ship for the AI given current resources and game phase."""
    constructor = constructors_by_team.get(team)
    if constructor is None or len(constructor.build_queue) >= 3:
        return
    mat = team_materials[team]

    own_miners = sum(1 for m in miners if m.team == team and m.alive)
    own_cargo  = sum(1 for c in cargo_ships if c.team == team and c.alive)

    # How many targets are actually worth mining right now?
    rich_asts   = [a for a in (asteroids or []) if hasattr(a, 'resources') and a.resources > 30]
    own_planets = (planets_by_team or {}).get(team, [])
    max_useful  = len(own_planets) + min(len(rich_asts), 2)
    miner_target = max(2, min(max_useful, 5))

    iron     = mat.get('iron',     0)
    copper   = mat.get('copper',   0)
    titanium = mat.get('titanium', 0)
    crystal  = mat.get('crystal',  0)
    fuel     = mat.get('fuel',     0)

    def can_afford(stype):
        return all(mat.get(m, 0) >= c for m, c in SHIP_COSTS.get(stype, {}).items())

    def can_afford_safely(stype):
        # Require 2× cost in stock so building doesn't drain the economy dry
        return all(mat.get(m, 0) >= c * 2 for m, c in SHIP_COSTS.get(stype, {}).items())

    def build(stype):
        constructor.queue_build(stype)
        for m, c in SHIP_COSTS.get(stype, {}).items():
            mat[m] -= c

    # ── Phase 1: establish economy ────────────────────────────────────────────
    if own_miners < miner_target and can_afford('MinerShip'):
        build('MinerShip'); return

    if own_cargo < max(1, own_miners) and can_afford('CargoShip'):
        build('CargoShip'); return

    # ── Phase 2: combat build, gated by having surplus resources ─────────────
    if titanium >= 30 and crystal >= 10 and fuel >= 40 and can_afford_safely('Carrier'):
        build('Carrier'); return

    if titanium >= 15 and copper >= 25 and can_afford_safely('Destroyer'):
        build('Destroyer'); return

    if copper >= 15 and can_afford('AICharacter'):
        build('AICharacter'); return

    # ── Phase 3: reinvest in economy when combat ships aren't yet affordable ──
    if iron >= 60 and own_miners < 5 and can_afford('MinerShip'):
        build('MinerShip'); return

    if own_cargo < own_miners and can_afford('CargoShip'):
        build('CargoShip')


def get_asteroid_at(asteroids, camera, sx, sy):
    """Return a mineable asteroid (GlowingAsteroid or MineableAsteroid) under (sx,sy)."""
    for a in asteroids:
        if not hasattr(a, 'planet_type'):
            continue
        ax, ay = camera.world_to_screen(a.wx + a.radius, a.wy + a.radius)
        if math.hypot(sx - ax, sy - ay) < max(12, int(a.radius * camera.zoom)):
            return a
    return None


def get_planet_at(solar_entities, camera, sx, sy):
    """Return the Planet under screen point (sx, sy), or None."""
    for e in solar_entities:
        if not isinstance(e, Planet):
            continue
        ex, ey = camera.world_to_screen(e.wx + e.radius, e.wy + e.radius)
        if math.hypot(sx - ex, sy - ey) < max(15, int(e.radius * camera.zoom)):
            return e
    return None


def _get_constructor_at_screen(solar_entities, camera, sx, sy):
    """Return the Constructor under screen point (sx, sy), or None."""
    for e in solar_entities:
        if not isinstance(e, Constructor):
            continue
        ex, ey = camera.world_to_screen(e.wx + e.radius, e.wy + e.radius)
        if math.hypot(sx - ex, sy - ey) < max(20, int(e.radius * camera.zoom)):
            return e
    return None


_QUEUE_DISPLAY_NAMES = {
    'AICharacter': 'Frigate', 'MinerShip': 'Miner',
    'CargoShip': 'Cargo', 'Destroyer': 'Destroyer', 'Carrier': 'Carrier',
}


def draw_build_menu(screen, constructor, team_materials, player_team):
    """Draw build menu + live queue panel.

    Returns (option_rects, cancel_rects, clear_rect):
      option_rects  — list of (ship_type, pygame.Rect)  build buttons
      cancel_rects  — list of (queue_index, pygame.Rect) per-item X buttons
      clear_rect    — pygame.Rect for the Clear All button (or None)
    """
    sw, sh   = screen.get_size()
    mat      = team_materials.get(player_team, {}) if team_materials else {}
    team_col = TEAM_COLORS[player_team]

    font_title = pygame.font.SysFont("impact",    20)
    font_row   = pygame.font.SysFont("monospace", 12)

    # ── Left panel: build options ────────────────────────────────────────────
    row_h    = 48
    panel_w  = 340
    panel_h  = 82 + len(_BUILD_MENU_ROWS) * row_h + 28
    px = sw - panel_w - 14
    py = sh // 2 - panel_h // 2

    bg = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
    bg.fill((6, 10, 22, 225))
    pygame.draw.rect(bg, (*team_col, 220), (0, 0, panel_w, panel_h), 2, border_radius=8)
    screen.blit(bg, (px, py))

    hdr = font_title.render("CONSTRUCTOR", True, team_col)
    screen.blit(hdr, (px + 10, py + 7))

    # Stock strip (two rows)
    stock_rows = [
        [('iron','Fe'), ('nickel','Ni'), ('copper','Cu'), ('silicon','Si'), ('ice','H₂O'), ('helium3','He³')],
        [('fuel','Fu'), ('titanium','Ti'), ('platinum','Pt'), ('crystal','Cr'), ('uranium','U')],
    ]
    sx0, sy0 = px + 8, py + 30
    for ri, row in enumerate(stock_rows):
        sx = sx0
        for mn, abbr in row:
            v   = int(mat.get(mn, 0))
            col = MATERIAL_COLOR.get(mn, (180, 180, 180))
            s   = font_row.render(f"{abbr}:{v}", True, col)
            screen.blit(s, (sx, sy0 + ri * 16))
            sx += s.get_width() + 8

    # Build rows
    option_rects = []
    y = py + 82
    for ship_type, label, costs in _BUILD_MENU_ROWS:
        can  = all(mat.get(m, 0) >= v for m, v in costs.items())
        rect = pygame.Rect(px + 6, y, panel_w - 12, row_h - 4)
        pygame.draw.rect(screen, (28, 48, 80) if can else (28, 18, 18), rect, border_radius=5)
        pygame.draw.rect(screen, (70, 140, 220) if can else (55, 35, 35), rect, 1, border_radius=5)
        lbl = font_row.render(label, True, (215, 215, 215) if can else (90, 70, 70))
        screen.blit(lbl, (rect.x + 8, rect.y + 4))
        cx = rect.x + 8
        for m, amt in costs.items():
            have     = mat.get(m, 0) >= amt
            chip_col = MATERIAL_COLOR.get(m, (180, 180, 180)) if have else (200, 70, 70)
            chip     = font_row.render(f"{MATERIAL_ABBREV.get(m, m)}:{amt}", True, chip_col)
            screen.blit(chip, (cx, rect.y + 24))
            cx += chip.get_width() + 8
        option_rects.append((ship_type, rect))
        y += row_h

    hint = font_row.render("[ESC] or click elsewhere to close", True, (70, 70, 95))
    screen.blit(hint, (px + 10, py + panel_h - 18))

    # ── Right panel: build queue ─────────────────────────────────────────────
    q_item_h  = 26
    q_panel_w = 160
    max_shown = 10
    queue     = constructor.build_queue
    n_shown   = min(len(queue), max_shown)
    q_panel_h = 34 + n_shown * q_item_h + (28 if queue else 0) + 28
    qpx = px - q_panel_w - 8
    qpy = py

    qbg = pygame.Surface((q_panel_w, q_panel_h), pygame.SRCALPHA)
    qbg.fill((6, 10, 22, 225))
    pygame.draw.rect(qbg, (*team_col, 180), (0, 0, q_panel_w, q_panel_h), 2, border_radius=8)
    screen.blit(qbg, (qpx, qpy))

    qhdr = font_title.render("QUEUE", True, team_col)
    screen.blit(qhdr, (qpx + 10, qpy + 7))

    cancel_rects = []
    clear_rect   = None

    if not queue:
        empty = font_row.render("(empty)", True, (80, 80, 100))
        screen.blit(empty, (qpx + 10, qpy + 34))
    else:
        qy = qpy + 34
        for i, stype in enumerate(queue[:max_shown]):
            label = _QUEUE_DISPLAY_NAMES.get(stype, stype)
            # Number badge
            num_s = font_row.render(f"{i+1}.", True, (120, 120, 140))
            screen.blit(num_s, (qpx + 6, qy + 5))
            # Label
            name_s = font_row.render(label, True, (210, 210, 210))
            screen.blit(name_s, (qpx + 24, qy + 5))
            # X cancel button
            x_rect = pygame.Rect(qpx + q_panel_w - 24, qy + 3, 18, 18)
            mx, my = pygame.mouse.get_pos()
            x_hover = x_rect.collidepoint(mx, my)
            pygame.draw.rect(screen, (140, 40, 40) if x_hover else (80, 28, 28),
                             x_rect, border_radius=3)
            pygame.draw.rect(screen, (220, 80, 80), x_rect, 1, border_radius=3)
            x_lbl = font_row.render("✕", True, (255, 120, 120))
            screen.blit(x_lbl, (x_rect.x + 3, x_rect.y + 2))
            cancel_rects.append((i, x_rect))
            # Divider
            if i < n_shown - 1:
                pygame.draw.line(screen, (30, 30, 50),
                                 (qpx + 4, qy + q_item_h - 1),
                                 (qpx + q_panel_w - 4, qy + q_item_h - 1))
            qy += q_item_h

        if len(queue) > max_shown:
            more = font_row.render(f"+ {len(queue) - max_shown} more…", True, (80, 80, 100))
            screen.blit(more, (qpx + 8, qy + 2))
            qy += 18

        # Clear All button
        clear_rect = pygame.Rect(qpx + 6, qy + 4, q_panel_w - 12, 20)
        mx, my = pygame.mouse.get_pos()
        c_hover = clear_rect.collidepoint(mx, my)
        pygame.draw.rect(screen, (100, 30, 30) if c_hover else (60, 18, 18),
                         clear_rect, border_radius=4)
        pygame.draw.rect(screen, (200, 70, 70), clear_rect, 1, border_radius=4)
        clbl = font_row.render("Clear All", True, (255, 100, 100))
        screen.blit(clbl, (clear_rect.x + (clear_rect.w - clbl.get_width()) // 2,
                           clear_rect.y + 2))

    return option_rects, cancel_rects, clear_rect


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_W, SCREEN_H), pygame.RESIZABLE)
    pygame.display.set_caption("Space Ranters")
    clock  = pygame.time.Clock()

    # ── Menu ──────────────────────────────────────────────────────────────────
    player_team = run_menu(screen, clock)

    # ── Loading screen → world + entities built in background thread ──────────
    world_surf, ai_characters, solar_entities, asteroids = run_loading_screen(screen, clock, player_team)
    camera = Camera(SCREEN_W, SCREEN_H)
    lasers:     list[Laser]     = []
    explosions: list[Explosion] = []

    # ── Resource & mining state ───────────────────────────────────────────────
    team_materials: dict = {
        t: {mat: float(STARTING_MATERIALS.get(mat, 0)) for mat in ALL_MATERIALS}
        for t in (0, 1)
    }
    miners:         list       = []
    constructors_by_team       = {e.team: e for e in solar_entities if isinstance(e, Constructor)}
    planets_by_team: dict      = {}
    for _e in solar_entities:
        if isinstance(_e, Planet):
            planets_by_team.setdefault(_e.team, []).append(_e)

    cargo_ships: list = []

    # Two free starting miners + one cargo ship per team
    for _team in (0, 1):
        _con = constructors_by_team.get(_team)
        if _con:
            for _ in range(2):
                miners.append(MinerShip(
                    _con.wx + _con.radius, _con.wy + _con.radius,
                    _team, planets_by_team.get(_team, []),
                ))
                miners[-1].asteroids = asteroids
            cargo_ships.append(CargoShip(
                _con.wx + _con.radius, _con.wy + _con.radius,
                _team, _con, miners, team_materials[_team],
            ))

    # AI team's starting miners auto-assign immediately
    _ai_team = 1 - player_team
    for _m in miners:
        if _m.team == _ai_team:
            _tp = planets_by_team.get(_ai_team, [])
            if _tp:
                _m.send_to(random.choice(_tp))

    constructor_menu_open          = False
    constructor_menu_ref           = None
    selected_planet                = None
    selected_asteroid              = None
    _build_menu_rects: list        = []   # (ship_type, rect) build buttons
    _build_cancel_rects: list      = []   # (queue_index, rect) X cancel buttons
    _build_clear_rects: list       = []   # 0 or 1 element: the Clear All rect
    ai_build_timer                 = 5.0  # seconds until next AI build check

    # Start camera centred on the player team's first carrier, or the home star.
    own_carriers = [s for s in ai_characters
                    if isinstance(s, Carrier) and s.team == player_team]
    if own_carriers:
        c = own_carriers[0]
        camera.follow(c.wx + c.width / 2, c.wy + c.height / 2)
    else:
        sx, sy = _team_star_position(player_team)
        camera.follow(sx, sy)

    # ── Enemy commander: trained neural network controlling the other team's
    #    fleet (falls back to the rule-based AICommander if no trained
    #    weights are found — see neural_commander.MODEL_PATH) ─────────────────
    enemy_team = 1 - player_team
    commander  = NeuralCommander(
        team=enemy_team, enemy_team=player_team,
        own_spawn=_team_spawn_center(enemy_team),
        enemy_spawn=_team_spawn_center(player_team),
        world_w=WORLD_W, world_h=WORLD_H,
    )

    # ── RTS state ─────────────────────────────────────────────────────────────
    selected_ships: list = []
    # player_orders: id(ship) → [order, ...] queue. order = {'ship_ref', 'type', ...}
    # types: 'move' {'pos'}, 'attack' {'target'}, 'attack_move' {'pos'}, 'follow' {'target','offset'}
    player_orders:  dict = {}
    control_groups: dict = {}   # 1-9 → list of ships
    DIGIT_KEYS = {
        pygame.K_1: 1, pygame.K_2: 2, pygame.K_3: 3, pygame.K_4: 4, pygame.K_5: 5,
        pygame.K_6: 6, pygame.K_7: 7, pygame.K_8: 8, pygame.K_9: 9,
    }

    lmb_start  = None   # LMB press position for click / box-select
    rmb_start  = None   # RMB press position for click vs. drag detection
    rmb_drag   = False  # True once RMB has moved enough to count as a pan
    drag_orig  = (0, 0) # Last drag position for incremental pan

    elapsed = 0.0
    # Command marker positions to show (list of (wx, wy))
    cmd_markers: list = []
    cmd_marker_t = 0.0  # countdown to remove markers

    # Quit-confirmation overlay — closing the window mid-battle pauses the
    # game instead of exiting instantly; closing it again actually quits.
    quit_confirm = False
    resume_button = None

    # HUD visibility (status panel, minimap, banner, control hints, and the
    # planet orbit guide-lines) — toggled with Tab for a clean battle view.
    hud_visible = True

    def render_frame():
        screen_w, screen_h = screen.get_size()
        vp_w = max(1, int(screen_w / camera.zoom))
        vp_h = max(1, int(screen_h / camera.zoom))
        vp_rect = pygame.Rect(int(camera.x), int(camera.y), vp_w, vp_h)
        vp_rect = vp_rect.clip(world_surf.get_rect())
        if vp_rect.width > 0 and vp_rect.height > 0:
            region = world_surf.subsurface(vp_rect)
            pygame.transform.scale(region, (screen_w, screen_h), screen)

        for asteroid in asteroids:
            asteroid.draw(screen, camera)

        for entity in solar_entities:
            if isinstance(entity, Planet):
                entity.draw(screen, camera, show_orbit=hud_visible)
            else:
                entity.draw(screen, camera)

        for ship in ai_characters:
            ship.draw(screen, camera)

        for miner in miners:
            miner.draw(screen, camera)

        for cargo in cargo_ships:
            cargo.draw(screen, camera)

        for laser in lasers:
            laser.draw(screen, camera)

        for exp in explosions:
            exp.draw(screen, camera)

        # Selection rings
        for ship in selected_ships:
            draw_selection_ring(screen, camera, ship, elapsed, player_team)


        # Command destination markers
        marker_col = TEAM_COLORS[player_team]
        for wx2, wy2 in cmd_markers:
            draw_command_marker(screen, camera, wx2, wy2, elapsed, marker_col)

        # Box-select overlay (while LMB held)
        if lmb_start is not None:
            draw_select_box(screen, lmb_start, pygame.mouse.get_pos())

        if hud_visible:
            draw_hud(screen, camera, ai_characters, player_team,
                     selected_ships, clock.get_fps(), screen_w, screen_h,
                     player_orders, team_materials)

        if hud_visible and selected_planet is not None:
            draw_planet_info(screen, selected_planet, screen_w)

        if hud_visible and selected_asteroid is not None and selected_asteroid.alive:
            draw_asteroid_info(screen, selected_asteroid, screen_w)

        if constructor_menu_open and constructor_menu_ref is not None:
            _opt, _cxl, _clr = draw_build_menu(
                screen, constructor_menu_ref, team_materials, player_team)
            _build_menu_rects[:]   = _opt
            _build_cancel_rects[:] = _cxl
            _build_clear_rects[:]  = [_clr] if _clr else []

    while True:
        dt        = clock.tick(FPS) / 1000.0
        elapsed  += dt
        screen_w, screen_h = screen.get_size()
        camera.screen_width  = screen_w
        camera.screen_height = screen_h
        mx, my = pygame.mouse.get_pos()

        # ── Quit confirmation: battle is paused, only the dialog responds ──────
        if quit_confirm:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    pygame.quit(); sys.exit()
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    quit_confirm = False
                if (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1
                        and resume_button and resume_button.collidepoint(event.pos)):
                    quit_confirm = False

            render_frame()
            resume_button = _draw_quit_confirm(screen, elapsed, (mx, my))
            pygame.display.flip()
            continue

        # ── Events ────────────────────────────────────────────────────────────
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                quit_confirm = True

            # ── Keyboard ──────────────────────────────────────────────────────
            if event.type == pygame.KEYDOWN:
                mods = pygame.key.get_mods()
                if event.key == pygame.K_ESCAPE:
                    if constructor_menu_open:
                        constructor_menu_open = False
                    else:
                        selected_ships.clear()
                        player_orders.clear()
                        cmd_markers.clear()
                if event.key == pygame.K_a and (mods & pygame.KMOD_CTRL):
                    selected_ships = [s for s in ai_characters
                                      if s.team == player_team and s.alive]

                # ── Control groups: Ctrl+1-9 assign, 1-9 recall ────────────────
                if event.key in DIGIT_KEYS:
                    grp = DIGIT_KEYS[event.key]
                    if mods & pygame.KMOD_CTRL:
                        if selected_ships:
                            control_groups[grp] = list(selected_ships)
                    else:
                        members = [s for s in control_groups.get(grp, []) if s.alive]
                        if members:
                            control_groups[grp] = members
                            if mods & pygame.KMOD_SHIFT:
                                for s in members:
                                    if s not in selected_ships:
                                        selected_ships.append(s)
                            else:
                                selected_ships = list(members)

                # ── Hold position: stay put, keep firing ───────────────────────
                if event.key == pygame.K_h and selected_ships:
                    new_hold = not all(s.player_hold for s in selected_ships)
                    for s in selected_ships:
                        s.player_hold = new_hold
                        if new_hold:
                            player_orders.pop(id(s), None)

                # ── Toggle hold fire ─────────────────────────────────────────
                if event.key == pygame.K_f and selected_ships:
                    new_hf = not all(s.hold_fire for s in selected_ships)
                    for s in selected_ships:
                        s.hold_fire = new_hf

                # ── Toggle HUD (status panel, minimap, hints, orbit lines) ─────
                if event.key == pygame.K_TAB:
                    hud_visible = not hud_visible

            # ── Zoom ──────────────────────────────────────────────────────────
            if event.type == pygame.MOUSEWHEEL:
                if event.y > 0:
                    new_zoom = min(camera.zoom * ZOOM_STEP, ZOOM_MAX)
                else:
                    new_zoom = max(camera.zoom / ZOOM_STEP, ZOOM_MIN)
                camera.zoom_toward(new_zoom, mx, my)

            # ── LMB: select / box-select ──────────────────────────────────────
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                lmb_start = event.pos

            if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                if lmb_start is not None:
                    ex, ey = event.pos
                    sx, sy = lmb_start
                    drag_dist = math.hypot(ex - sx, ey - sy)
                    mods = pygame.key.get_mods()

                    if drag_dist < 8:
                        if constructor_menu_open:
                            _clicked_menu = False
                            # Clear All button
                            if _build_clear_rects and _build_clear_rects[0].collidepoint(ex, ey):
                                constructor_menu_ref.build_queue.clear()
                                _clicked_menu = True
                            # Per-item cancel (X) buttons — iterate in reverse so
                            # removing by index doesn't shift earlier items
                            if not _clicked_menu:
                                for _qi, _qr in reversed(_build_cancel_rects):
                                    if _qr.collidepoint(ex, ey):
                                        if 0 <= _qi < len(constructor_menu_ref.build_queue):
                                            constructor_menu_ref.build_queue.pop(_qi)
                                        _clicked_menu = True
                                        break
                            # Build option buttons
                            if not _clicked_menu:
                                for _stype, _rect in _build_menu_rects:
                                    if _rect.collidepoint(ex, ey):
                                        _c  = SHIP_COSTS.get(_stype, {})
                                        _pm = team_materials[player_team]
                                        if all(_pm.get(m, 0) >= v for m, v in _c.items()):
                                            for m, v in _c.items():
                                                _pm[m] -= v
                                            constructor_menu_ref.queue_build(_stype)
                                        _clicked_menu = True
                                        break
                            # Only close on clicks outside all menu panels
                            if not _clicked_menu:
                                constructor_menu_open = False
                        else:
                            selected_planet   = None
                            selected_asteroid = None
                            # Constructor click opens the build menu
                            _con_hit = _get_constructor_at_screen(
                                solar_entities, camera, ex, ey)
                            if _con_hit is not None and _con_hit.team == player_team:
                                constructor_menu_open = True
                                constructor_menu_ref  = _con_hit
                            else:
                                # Planet click shows info panel
                                _planet_hit = get_planet_at(solar_entities, camera, ex, ey)
                                if _planet_hit is not None:
                                    selected_planet = _planet_hit
                                    selected_ships.clear()
                                else:
                                    # Asteroid click shows info panel
                                    _asteroid_hit = get_asteroid_at(asteroids, camera, ex, ey)
                                    if _asteroid_hit is not None:
                                        selected_asteroid = _asteroid_hit
                                        selected_ships.clear()
                                    else:
                                        # Normal ship selection (includes miners)
                                        clicked = get_ship_at(ai_characters + miners, camera, ex, ey)
                                        if clicked is None:
                                            if not (mods & pygame.KMOD_SHIFT):
                                                selected_ships.clear()
                                        elif clicked.team == player_team:
                                            if mods & pygame.KMOD_SHIFT:
                                                if clicked in selected_ships:
                                                    selected_ships.remove(clicked)
                                                else:
                                                    selected_ships.append(clicked)
                                            else:
                                                selected_ships = [clicked]
                                        elif not (mods & pygame.KMOD_SHIFT):
                                            selected_ships.clear()
                    else:
                        # Box select — only friendly ships
                        box = pygame.Rect(min(sx, ex), min(sy, ey),
                                          abs(ex - sx), abs(ey - sy))
                        found = get_ships_in_box(
                            [s for s in ai_characters + miners
                             if s.team == player_team and s.alive],
                            camera, box,
                        )
                        if not (mods & pygame.KMOD_SHIFT):
                            selected_ships.clear()
                        for s in found:
                            if s not in selected_ships:
                                selected_ships.append(s)
                lmb_start = None

            # ── RMB: pan (drag) or command (click) ────────────────────────────
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 3:
                rmb_start = event.pos
                rmb_drag  = False
                drag_orig = event.pos

            if event.type == pygame.MOUSEMOTION:
                if rmb_start is not None:
                    moved = math.hypot(event.pos[0] - rmb_start[0],
                                       event.pos[1] - rmb_start[1])
                    if moved > 8:
                        rmb_drag = True
                    if rmb_drag:
                        ddx = drag_orig[0] - event.pos[0]
                        ddy = drag_orig[1] - event.pos[1]
                        camera.move(ddx / camera.zoom, ddy / camera.zoom)
                    drag_orig = event.pos

            if event.type == pygame.MOUSEBUTTONUP and event.button == 3:
                if rmb_start is not None and not rmb_drag and selected_ships:
                    # Short click → issue command
                    cx_s, cy_s = rmb_start
                    mods       = pygame.key.get_mods()
                    queueing   = bool(mods & pygame.KMOD_SHIFT)
                    attack_move_mod = pygame.key.get_pressed()[pygame.K_a]

                    clicked = get_ship_at(ai_characters, camera, cx_s, cy_s)
                    target_enemy = clicked if (clicked is not None
                                                and clicked.team != player_team) else None
                    target_ally  = clicked if (clicked is not None
                                                and clicked.team == player_team
                                                and clicked not in selected_ships) else None
                    wx, wy = camera.screen_to_world(cx_s, cy_s)

                    if not queueing:
                        cmd_markers.clear()
                        for s in selected_ships:
                            if hasattr(s, 'player_hold'):
                                s.player_hold = False

                    # ── Miner → planet or asteroid assignment ─────────────────
                    _clicked_planet   = get_planet_at(solar_entities, camera, cx_s, cy_s)
                    _clicked_asteroid = (get_asteroid_at(asteroids, camera, cx_s, cy_s)
                                         if _clicked_planet is None else None)
                    _clicked_target   = _clicked_planet or _clicked_asteroid
                    _sel_miners = [s for s in selected_ships
                                   if isinstance(s, MinerShip) and s.team == player_team]
                    if _clicked_target is not None and _sel_miners:
                        _tgt_team = getattr(_clicked_target, 'team', None)
                        if _tgt_team == player_team or _tgt_team is None:
                            for _m in _sel_miners:
                                _m.send_to(_clicked_target)
                            cmd_markers.append(
                                (_clicked_target.wx + _clicked_target.radius,
                                 _clicked_target.wy + _clicked_target.radius))

                    # ── Detect click on friendly cargo ship ───────────────────
                    _clicked_cargo = None
                    if target_enemy is None:
                        for _c in cargo_ships:
                            if _c.team == player_team and _c.alive:
                                _ccx, _ccy = camera.world_to_screen(
                                    _c.wx + _c.width / 2, _c.wy + _c.height / 2)
                                if math.hypot(cx_s - _ccx, cy_s - _ccy) < max(14, int(
                                        math.hypot(_c.width, _c.height) / 2 * camera.zoom)):
                                    _clicked_cargo = _c
                                    break

                    # ── Detect click on friendly miner ship ────────────────────
                    _clicked_miner = None
                    if target_enemy is None and _clicked_cargo is None:
                        for _mn in miners:
                            if _mn.team == player_team and _mn.alive:
                                _mcx, _mcy = camera.world_to_screen(
                                    _mn.wx + _mn.width / 2, _mn.wy + _mn.height / 2)
                                if math.hypot(cx_s - _mcx, cy_s - _mcy) < max(14, int(
                                        math.hypot(_mn.width, _mn.height) / 2 * camera.zoom + 8)):
                                    _clicked_miner = _mn
                                    break

                    # ── Cargo ship → specific miner assignment ────────────────
                    _sel_cargos = [s for s in selected_ships
                                   if isinstance(s, CargoShip) and s.team == player_team]
                    if _sel_cargos:
                        if _clicked_miner is not None and _clicked_miner.team == player_team:
                            # Shift = add to pool; no shift = replace pool
                            for _cs in _sel_cargos:
                                if queueing:
                                    if _cs._assigned_miners is None:
                                        _cs._assigned_miners = [_clicked_miner]
                                    elif _clicked_miner not in _cs._assigned_miners:
                                        _cs._assigned_miners.append(_clicked_miner)
                                else:
                                    _cs._assigned_miners = [_clicked_miner]
                            cmd_markers.append((
                                _clicked_miner.wx + _clicked_miner.width  / 2,
                                _clicked_miner.wy + _clicked_miner.height / 2,
                            ))
                        elif (_clicked_target is None and target_enemy is None
                              and _clicked_cargo is None and _clicked_miner is None):
                            # Right-click empty space = clear back to automatic routing
                            for _cs in _sel_cargos:
                                _cs._assigned_miners = None

                    # ── Combat orders — miners excluded ────────────────────────
                    _combat_sel = [s for s in selected_ships
                                   if not isinstance(s, MinerShip)
                                   and not isinstance(s, CargoShip)]
                    if _combat_sel:
                        cxs   = [s.wx + s.width  / 2 for s in _combat_sel]
                        cys   = [s.wy + s.height / 2 for s in _combat_sel]
                        cen_x = sum(cxs) / len(cxs)
                        cen_y = sum(cys) / len(cys)

                        if (_clicked_planet is not None
                                and getattr(_clicked_planet, 'team', None) == player_team
                                and target_enemy is None):
                            # ── Guard planet ───────────────────────────────────
                            for s in _combat_sel:
                                s.deployed = True
                                # Release any active escort assignment
                                _oq = player_orders.get(id(s), [])
                                if _oq and _oq[0].get('type') == 'escort':
                                    if s.fleet_leader is _oq[0].get('target'):
                                        s.fleet_leader = None
                                order = {'ship_ref': s, 'type': 'guard_planet',
                                         'planet': _clicked_planet}
                                if queueing:
                                    player_orders.setdefault(id(s), []).append(order)
                                else:
                                    player_orders[id(s)] = [order]
                            cmd_markers.append((_clicked_planet.wx + _clicked_planet.radius,
                                                _clicked_planet.wy + _clicked_planet.radius))

                        elif _clicked_cargo is not None and target_enemy is None:
                            # ── Escort cargo ship ──────────────────────────────
                            cargo_cx = _clicked_cargo.wx + _clicked_cargo.width  / 2
                            cargo_cy = _clicked_cargo.wy + _clicked_cargo.height / 2
                            for s, scx, scy in zip(_combat_sel, cxs, cys):
                                s.deployed = True
                                raw_ox = scx - cargo_cx
                                raw_oy = scy - cargo_cy
                                d = math.hypot(raw_ox, raw_oy)
                                if d < 50:
                                    raw_ox, raw_oy = 280.0, 0.0
                                elif d > 600:
                                    scale = 450.0 / d
                                    raw_ox, raw_oy = raw_ox * scale, raw_oy * scale
                                order = {
                                    'ship_ref': s, 'type': 'escort',
                                    'target': _clicked_cargo,
                                    'offset': (raw_ox, raw_oy),
                                }
                                if queueing:
                                    player_orders.setdefault(id(s), []).append(order)
                                else:
                                    player_orders[id(s)] = [order]
                            cmd_markers.append((cargo_cx, cargo_cy))

                        elif _clicked_miner is not None and target_enemy is None:
                            # ── Escort miner ship ──────────────────────────────
                            miner_cx = _clicked_miner.wx + _clicked_miner.width  / 2
                            miner_cy = _clicked_miner.wy + _clicked_miner.height / 2
                            for s, scx, scy in zip(_combat_sel, cxs, cys):
                                s.deployed = True
                                raw_ox = scx - miner_cx
                                raw_oy = scy - miner_cy
                                d = math.hypot(raw_ox, raw_oy)
                                if d < 50:
                                    raw_ox, raw_oy = 260.0, 0.0
                                elif d > 600:
                                    scale = 420.0 / d
                                    raw_ox, raw_oy = raw_ox * scale, raw_oy * scale
                                order = {
                                    'ship_ref': s, 'type': 'escort',
                                    'target': _clicked_miner,
                                    'offset': (raw_ox, raw_oy),
                                }
                                if queueing:
                                    player_orders.setdefault(id(s), []).append(order)
                                else:
                                    player_orders[id(s)] = [order]
                            cmd_markers.append((miner_cx, miner_cy))

                        else:
                            # ── Normal combat orders ───────────────────────────
                            for s, scx, scy in zip(_combat_sel, cxs, cys):
                                s.deployed = True
                                # Release any active escort assignment
                                _oq = player_orders.get(id(s), [])
                                if _oq and _oq[0].get('type') == 'escort':
                                    if s.fleet_leader is _oq[0].get('target'):
                                        s.fleet_leader = None
                                if target_enemy is not None:
                                    order = {'ship_ref': s, 'type': 'attack',
                                             'target': target_enemy}
                                elif target_ally is not None:
                                    order = {
                                        'ship_ref': s, 'type': 'follow',
                                        'target': target_ally,
                                        'offset': (scx - (target_ally.wx + target_ally.width / 2),
                                                   scy - (target_ally.wy + target_ally.height / 2)),
                                    }
                                else:
                                    dest = (wx + (scx - cen_x), wy + (scy - cen_y))
                                    order = {
                                        'ship_ref': s,
                                        'type':     'attack_move' if attack_move_mod else 'move',
                                        'pos':      dest,
                                    }
                                    cmd_markers.append(dest)

                                if queueing:
                                    player_orders.setdefault(id(s), []).append(order)
                                else:
                                    player_orders[id(s)] = [order]

                            if target_enemy is not None:
                                tx = target_enemy.wx + target_enemy.width  / 2
                                ty = target_enemy.wy + target_enemy.height / 2
                                cmd_markers.append((tx, ty))
                            elif target_ally is not None:
                                tx = target_ally.wx + target_ally.width  / 2
                                ty = target_ally.wy + target_ally.height / 2
                                cmd_markers.append((tx, ty))

                    cmd_marker_t = 2.5   # show markers for 2.5 seconds

                rmb_start = None
                rmb_drag  = False

        if quit_confirm:
            # Window close requested this frame — drop straight into the
            # paused dialog without advancing simulation or drawing the HUD.
            render_frame()
            resume_button = _draw_quit_confirm(screen, elapsed, (mx, my))
            pygame.display.flip()
            continue

        # ── Solar-system update: stars, planets, constructors
        built_ships = []
        for entity in solar_entities:
            result = entity.update(dt)
            if result is not None:
                build_type, sx, sy, team = result

                if build_type == 'MinerShip':
                    miners.append(MinerShip(
                        sx, sy, team, planets_by_team.get(team, []),
                    ))
                    miners[-1].asteroids = asteroids
                    continue

                if build_type == 'CargoShip':
                    _con = constructors_by_team.get(team)
                    if _con:
                        cargo_ships.append(CargoShip(
                            sx, sy, team, _con, miners,
                            team_materials[team],
                        ))
                    continue

                wp = _make_waypoints(team)
                if build_type == 'Carrier':
                    ship = Carrier(sx, sy, wp, team=team)
                elif build_type == 'Destroyer':
                    ship = Destroyer(sx, sy, wp, team=team)
                else:
                    ship = AICharacter(sx, sy, wp, team=team)
                ship.wx -= ship.width / 2
                ship.wy -= ship.height / 2
                ship.deployed = False
                ship.home_pos = (ship.wx + ship.width / 2, ship.wy + ship.height / 2)

                if build_type == 'Carrier':
                    ship.fleet_leader = ship
                else:
                    leader = next(
                        (s for s in reversed(ai_characters + built_ships)
                         if isinstance(s, Carrier) and s.team == team and s.alive),
                        None,
                    )
                    if leader is not None:
                        ship.fleet_leader = leader
                        if build_type == 'Destroyer':
                            n = sum(1 for s in ai_characters
                                    if s.fleet_leader is leader and isinstance(s, Destroyer))
                            ship.fleet_offset = (0.0, (1 if n % 2 == 0 else -1) * 550.0)
                            ship.fleet_stray_dist = 900.0
                        else:
                            n = sum(1 for s in ai_characters
                                    if s.fleet_leader is leader
                                    and isinstance(s, AICharacter)
                                    and not isinstance(s, (Carrier, Destroyer, Fighter)))
                            angle = n * (math.tau / 6)
                            radius = 280 + (n // 6) * 100
                            ship.fleet_offset = (math.cos(angle) * radius,
                                                 math.sin(angle) * radius)
                            ship.fleet_stray_dist = 450.0

                built_ships.append(ship)
        if built_ships:
            ai_characters.extend(built_ships)

        # ── Update ────────────────────────────────────────────────────────────
        for ship in ai_characters:
            ship.update(dt)
            ship.wx = max(0.0, min(WORLD_W - ship.width,  ship.wx))
            ship.wy = max(0.0, min(WORLD_H - ship.height, ship.wy))

        update_team_strategy(ai_characters)

        alive_before = {id(s): s.alive for s in ai_characters}
        _combat_targets = ai_characters + [m for m in miners if m.alive] + [c for c in cargo_ships if c.alive]
        for ship in ai_characters:
            ship.update_combat(dt, _combat_targets, lasers)

        # Enemy commander — decides when its fleet deploys and where it
        # rallies, then steers idle ("patrol") fleet leaders toward that order.
        commander.update(dt, ai_characters)

        # Reset per-frame escort flags (re-set by active escort orders below).
        for _c in cargo_ships:
            _c._needs_defense = False
        for _m in miners:
            _m._needs_defense = False

        # Apply player orders — override combat AI's movement destination.
        # Each ship has a queue; the head order is "current" and advances
        # (pops) once satisfied, automatically starting the next queued one.
        to_clear = []
        for ship_id, queue in player_orders.items():
            if not queue:
                to_clear.append(ship_id)
                continue
            ref = queue[0]['ship_ref']
            if not ref.alive or ref.player_hold:
                to_clear.append(ship_id)
                continue

            order    = queue[0]
            finished = False

            if order['type'] == 'move':
                px, py = order['pos']
                ref._movement_override = (px, py)
                cx2 = ref.wx + ref.width  / 2
                cy2 = ref.wy + ref.height / 2
                if math.hypot(cx2 - px, cy2 - py) < 200:
                    finished = True                   # arrived — release the order

            elif order['type'] == 'attack_move':
                px, py = order['pos']
                if ref._current_target is None:
                    # No contact yet (or contact cleared) — keep advancing
                    ref._movement_override = (px, py)
                    cx2 = ref.wx + ref.width  / 2
                    cy2 = ref.wy + ref.height / 2
                    if math.hypot(cx2 - px, cy2 - py) < 200:
                        finished = True
                # else: an enemy was spotted — leave the combat AI's own
                # engage/flank movement in place until the fight is resolved.

            elif order['type'] == 'attack':
                tgt = order['target']
                if not tgt.alive:
                    finished = True
                else:
                    tx2 = tgt.wx + tgt.width  / 2
                    ty2 = tgt.wy + tgt.height / 2
                    ref._movement_override = (tx2, ty2)   # keep chasing

            elif order['type'] == 'follow':
                tgt = order['target']
                if not tgt.alive:
                    finished = True
                else:
                    ox, oy = order['offset']
                    ref._movement_override = (tgt.wx + tgt.width  / 2 + ox,
                                               tgt.wy + tgt.height / 2 + oy)

            elif order['type'] == 'guard_planet':
                planet = order['planet']
                if hasattr(planet, 'alive') and not planet.alive:
                    finished = True
                else:
                    order['_orbit_angle'] = order.get('_orbit_angle', 0.0) + 0.28 * dt
                    if ref._current_target is None or not getattr(ref._current_target, 'alive', False):
                        # Orbit the planet when not in combat
                        pcx = planet.wx + planet.radius
                        pcy = planet.wy + planet.radius
                        guard_r = planet.radius + 400.0
                        ref._movement_override = (
                            pcx + math.cos(order['_orbit_angle']) * guard_r,
                            pcy + math.sin(order['_orbit_angle']) * guard_r,
                        )
                    # else: combat AI is handling movement — don't override it

            elif order['type'] == 'escort':
                tgt = order['target']
                if not tgt.alive:
                    if ref.fleet_leader is tgt:
                        ref.fleet_leader = None
                    finished = True
                else:
                    # Bind fleet_leader so combat AI's fleet-cohesion follows the cargo ship
                    ref.fleet_leader  = tgt
                    ref.fleet_offset  = order['offset']
                    tgt._needs_defense = True

            if finished:
                queue.pop(0)
                if not queue:
                    to_clear.append(ship_id)

        for ship_id in to_clear:
            player_orders.pop(ship_id, None)

        # Prune dead ships from selection
        selected_ships = [s for s in selected_ships if s.alive]

        # Explosions for ships that just died
        for ship in ai_characters:
            if alive_before.get(id(ship)) and not ship.alive:
                explosions.append(Explosion(
                    ship.wx + ship.width  / 2,
                    ship.wy + ship.height / 2,
                    ship.width, ship.height,
                ))

        # Carrier fighter spawns
        new_fighters = []
        for ship in ai_characters:
            if isinstance(ship, Carrier) and ship._spawn_queue:
                for fx, fy, fteam in ship._spawn_queue:
                    wp      = _make_waypoints()
                    fighter = Fighter(fx, fy, wp, fteam, home_carrier=ship)
                    fighter.fleet_leader = ship
                    fighter.deployed     = True   # launched into action, not idling
                    angle = random.uniform(0, math.tau)
                    fighter.fleet_offset = (math.cos(angle) * 200, math.sin(angle) * 200)
                    ship._active_fighters.append(fighter)
                    new_fighters.append(fighter)
                ship._spawn_queue.clear()
        if new_fighters:
            ai_characters.extend(new_fighters)

        # ── Global separation pass — all same-team ships push apart ──────────
        _sep_pool = [s for s in (ai_characters + miners + cargo_ships)
                     if getattr(s, 'alive', True)]
        for _si, _sa in enumerate(_sep_pool):
            _cx_a = _sa.wx + _sa.width  / 2
            _cy_a = _sa.wy + _sa.height / 2
            for _sb in _sep_pool[_si + 1:]:
                if _sa.team != _sb.team:
                    continue
                _cx_b = _sb.wx + _sb.width  / 2
                _cy_b = _sb.wy + _sb.height / 2
                _d = math.hypot(_cx_b - _cx_a, _cy_b - _cy_a)
                if 0 < _d < _SHIP_SEP_DIST:
                    _str = (_SHIP_SEP_DIST - _d) / _SHIP_SEP_DIST * _SHIP_SEP_FORCE
                    _nx  = (_cx_a - _cx_b) / _d
                    _ny  = (_cy_a - _cy_b) / _d
                    _sa._sep_ax += _nx * _str
                    _sa._sep_ay += _ny * _str
                    _sb._sep_ax -= _nx * _str
                    _sb._sep_ay -= _ny * _str

        # Miner tick
        for miner in miners:
            miner.update(dt)
            miner.wx = max(0.0, min(WORLD_W - miner.width,  miner.wx))
            miner.wy = max(0.0, min(WORLD_H - miner.height, miner.wy))
        miners[:] = [m for m in miners if m.alive]

        for cargo in cargo_ships:
            cargo.update(dt)
            cargo.wx = max(0.0, min(WORLD_W - cargo.width,  cargo.wx))
            cargo.wy = max(0.0, min(WORLD_H - cargo.height, cargo.wy))
        cargo_ships[:] = [c for c in cargo_ships if c.alive]

        # AI build queuing
        ai_build_timer -= dt
        if ai_build_timer <= 0.0:
            ai_build_timer = 6.0
            _ai_queue_build(enemy_team, constructors_by_team, miners, cargo_ships,
                            team_materials)
            # Assign any AI miners that are still idle (planets + asteroids)
            _ai_targets = planets_by_team.get(enemy_team, []) + [
                a for a in asteroids if hasattr(a, 'planet_type')]
            if _ai_targets:
                for _m in miners:
                    if _m.team == enemy_team and _m.alive and _m.state == 'idle':
                        _m.send_to(random.choice(_ai_targets))

        # Asteroid field tick
        for asteroid in asteroids:
            asteroid.update(dt)

        # Prune exhausted asteroids then respawn if counts fall below minimums
        asteroids[:] = [a for a in asteroids if getattr(a, 'alive', True)]
        _ore_count  = sum(1 for a in asteroids if isinstance(a, MineableAsteroid))
        _glow_count = sum(1 for a in asteroids if isinstance(a, GlowingAsteroid))
        if _ore_count < _RESPAWN_MIN_ORE or _glow_count < _RESPAWN_MIN_GLOW:
            _diag = math.sqrt(WORLD_W ** 2 + WORLD_H ** 2)
            _px   = WORLD_H / _diag
            _py   = WORLD_W / _diag
            for _ in range(_RESPAWN_MIN_ORE - _ore_count):
                t   = random.uniform(0.08, 0.92)
                off = random.uniform(-480, 480)
                mx  = max(100.0, min(WORLD_W - 100, WORLD_W * (1 - t) + off * _px))
                my  = max(100.0, min(WORLD_H - 100, WORLD_H * t       + off * _py))
                asteroids.append(MineableAsteroid(mx, my))
            for _ in range(_RESPAWN_MIN_GLOW - _glow_count):
                t   = random.uniform(0.08, 0.92)
                off = random.uniform(-480, 480)
                gx  = max(100.0, min(WORLD_W - 100, WORLD_W * (1 - t) + off * _px))
                gy  = max(100.0, min(WORLD_H - 100, WORLD_H * t       + off * _py))
                asteroids.append(GlowingAsteroid(gx, gy))

        # Re-assign player miners that went idle because their asteroid depleted.
        # Once a miner is in asteroid_mode it should keep mining like a planet miner would.
        _avail_asteroids = [a for a in asteroids if getattr(a, 'resources', 1) > 0]
        if _avail_asteroids:
            for _m in miners:
                if (_m.team == player_team and _m.alive
                        and _m.state == 'idle' and _m._asteroid_mode):
                    _m.send_to(random.choice(_avail_asteroids))

        # Laser and explosion ticks
        for laser in lasers:
            laser.update(dt)
        lasers[:] = [l for l in lasers if l.alive]

        for exp in explosions:
            exp.update(dt)
        explosions[:] = [e for e in explosions if e.alive]

        # Command marker countdown
        if cmd_marker_t > 0:
            cmd_marker_t -= dt
            if cmd_marker_t <= 0:
                cmd_markers.clear()

        camera.clamp(WORLD_W, WORLD_H)

        # ── Draw ──────────────────────────────────────────────────────────────
        render_frame()
        pygame.display.flip()


if __name__ == "__main__":
    main()
