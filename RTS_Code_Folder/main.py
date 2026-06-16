"""
main.py — Space Ranters: RTS fleet commander.

Main Menu  → choose Blue or Red team.
In-game    → command your fleet to destroy the enemy.

Controls (in-game):
  LMB click        — select a friendly ship
  LMB drag         — box-select multiple ships
  Shift + LMB      — add / remove from selection
  RMB click        — move order (empty space) or attack order (enemy ship)
  RMB drag         — pan camera
  Scroll wheel     — zoom in / out
  Ctrl+A           — select all your ships
  Escape           — deselect all
"""

import sys
import math
import random
import threading
import pygame
from camera import Camera
from entities import AICharacter, Laser, Explosion, Fighter, Carrier, Destroyer

# ── Display ───────────────────────────────────────────────────────────────────
SCREEN_W, SCREEN_H = 1000, 800

# ── World ─────────────────────────────────────────────────────────────────────
map_scale_factor = 4
WORLD_W = 4000 * map_scale_factor
WORLD_H = 3200 * map_scale_factor

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
        'done':          False,
    }

    def _load():
        state['step']     = 'Building star map…'
        state['progress'] = 0.03
        state['world_surf'] = build_world_surface(state)   # updates progress 0.05→0.55

        state['step']     = 'Deploying fleets…'
        state['progress'] = 0.60
        state['ai_characters'] = setup_game()

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
    return state['world_surf'], state['ai_characters']


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

    # Quit hint
    hint = font_hint.render("ESC — Quit", True, (60, 60, 80))
    screen.blit(hint, hint.get_rect(center=(sw // 2, by + btn_h + 30)))

    return btn_rects


def run_menu(screen, clock):
    """Show the main menu; return chosen team index (0=blue, 1=red)."""
    stars   = _make_menu_stars()
    elapsed = 0.0
    while True:
        dt = clock.tick(60) / 1000.0
        elapsed += dt
        mx, my = pygame.mouse.get_pos()

        hovered = None
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit(); sys.exit()
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                pygame.quit(); sys.exit()
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                btn_rects = _draw_menu(screen, stars, elapsed, hovered)
                for i, rect in enumerate(btn_rects):
                    if rect.collidepoint(event.pos):
                        return i   # 0 = blue, 1 = red

        btn_rects = _draw_menu(screen, stars, elapsed, hovered)
        for i, rect in enumerate(btn_rects):
            if rect.collidepoint((mx, my)):
                hovered = i

        pygame.display.flip()


# ── Game setup ────────────────────────────────────────────────────────────────
def _make_waypoints():
    return [(random.randint(200, WORLD_W - 200),
             random.randint(200, WORLD_H - 200)) for _ in range(5)]


def setup_game():
    NUM_CARRIERS_PER_TEAM  = max(1, NUM_AI // 25)
    NUM_DESTROYERS_PER_TEAM = 2

    ai_characters = []
    for i in range(NUM_AI):
        team      = 0 if i < NUM_AI // 2 else 1
        team_slot = i if team == 0 else i - NUM_AI // 2
        wp        = _make_waypoints()
        if team_slot < NUM_CARRIERS_PER_TEAM:
            ai_characters.append(Carrier(wp[0][0], wp[0][1], wp, team=team))
        else:
            ai_characters.append(AICharacter(wp[0][0], wp[0][1], wp, team=team))

    for team in (0, 1):
        team_carriers = [s for s in ai_characters
                         if isinstance(s, Carrier) and s.team == team]
        for i in range(NUM_DESTROYERS_PER_TEAM):
            wp = _make_waypoints()
            d  = Destroyer(wp[0][0], wp[0][1], wp, team=team)
            if team_carriers:
                leader = team_carriers[i % len(team_carriers)]
                d.fleet_leader     = leader
                d.fleet_offset     = (0.0, (1 if i % 2 == 0 else -1) * 550.0)
                d.fleet_stray_dist = 900.0
            ai_characters.append(d)

    ESCORTS_PER_FLEET = 3
    for team in (0, 1):
        carriers  = [s for s in ai_characters if isinstance(s, Carrier) and s.team == team]
        non_carry = [s for s in ai_characters
                     if not isinstance(s, Carrier) and s.team == team]
        if not carriers:
            continue
        for carrier in carriers:
            carrier.fleet_leader = carrier
        for i, ship in enumerate(non_carry):
            leader     = carriers[i % len(carriers)]
            fleet_slot = i // len(carriers)
            ship.fleet_leader = leader
            if fleet_slot < ESCORTS_PER_FLEET:
                angle  = fleet_slot * (math.tau / ESCORTS_PER_FLEET)
                radius = 260
                ship.fleet_stray_dist = 380
                ship.role = 'attacker'
            else:
                slot   = fleet_slot - ESCORTS_PER_FLEET
                angle  = slot * 2.39996
                radius = 300 + (slot % 4) * 130
            ship.fleet_offset = (math.cos(angle) * radius, math.sin(angle) * radius)

    return ai_characters


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


def draw_select_box(surface, start, end):
    if start is None:
        return
    x0, y0 = start
    x1, y1 = end
    bx, by = min(x0, x1), min(y0, y1)
    bw, bh = abs(x1 - x0), abs(y1 - y0)
    if bw < 2 or bh < 2:
        return
    box = pygame.Surface((bw, bh), pygame.SRCALPHA)
    box.fill((80, 160, 255, 25))
    pygame.draw.rect(box, (80, 160, 255, 180), (0, 0, bw, bh), 1)
    surface.blit(box, (bx, by))


# ── HUD ───────────────────────────────────────────────────────────────────────
def draw_hud(screen, camera, ai_characters, player_team, selected_ships,
             fps, screen_w, screen_h, player_orders):
    font_sm  = pygame.font.SysFont("monospace", 14)
    font_med = pygame.font.SysFont("monospace", 16)

    team_col   = TEAM_COLORS[player_team]
    enemy_team = 1 - player_team

    friendly = [s for s in ai_characters if s.team == player_team and s.alive]
    enemy    = [s for s in ai_characters if s.team == enemy_team  and s.alive]
    f_carr   = sum(1 for s in friendly if isinstance(s, Carrier))
    e_carr   = sum(1 for s in enemy   if isinstance(s, Carrier))

    # ── Top-left status panel ─────────────────────────────────────────────────
    lines = [
        f"FPS: {fps:.0f}",
        "",
        f"YOUR FLEET:  {len(friendly):3d} ships  ({f_carr} carriers)",
        f"ENEMY FLEET: {len(enemy):3d} ships  ({e_carr} carriers)",
        "",
        f"SELECTED: {len(selected_ships)} ship{'s' if len(selected_ships) != 1 else ''}",
        f"ORDERS ACTIVE: {len(player_orders)}",
    ]
    panel_w = 290
    panel_h = len(lines) * 18 + 14
    panel = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
    panel.fill((0, 0, 0, 155))
    # Team colour strip on left edge
    pygame.draw.rect(panel, (*team_col, 200), (0, 0, 4, panel_h))
    for i, line in enumerate(lines):
        if i == 2:
            col = team_col
        elif i == 3:
            col = TEAM_COLORS[enemy_team]
        elif i == 5 and selected_ships:
            col = (220, 220, 100)
        else:
            col = (160, 160, 180)
        panel.blit(font_sm.render(line, True, col), (10, 7 + i * 18))
    screen.blit(panel, (8, 8))

    # ── Selected ship detail (bottom centre) ──────────────────────────────────
    if selected_ships:
        types = {}
        for s in selected_ships:
            t = type(s).__name__
            types[t] = types.get(t, 0) + 1
        type_str = "  ".join(f"{v}× {k}" for k, v in types.items())
        detail = font_med.render(type_str, True, (220, 220, 100))
        dx     = screen_w // 2 - detail.get_width() // 2
        bg     = pygame.Surface((detail.get_width() + 20, 28), pygame.SRCALPHA)
        bg.fill((0, 0, 0, 160))
        screen.blit(bg,    (dx - 10, screen_h - 46))
        screen.blit(detail, (dx, screen_h - 42))

    # ── Controls hint (bottom-left) ───────────────────────────────────────────
    hints = [
        "LMB: Select   Shift+LMB: Add/Remove",
        "Drag LMB: Box select   Ctrl+A: All",
        "RMB click: Move/Attack   RMB drag: Pan",
        "Scroll: Zoom   ESC: Deselect",
    ]
    hint_y = screen_h - len(hints) * 16 - 8
    for i, h in enumerate(hints):
        surf = font_sm.render(h, True, (80, 80, 100))
        screen.blit(surf, (8, hint_y + i * 16))

    # ── Minimap ───────────────────────────────────────────────────────────────
    mm_w, mm_h = 180, 120
    mm_x = screen_w - mm_w - 10
    mm_y = 10
    mm   = pygame.Surface((mm_w, mm_h), pygame.SRCALPHA)
    mm.fill((0, 0, 0, 170))
    pygame.draw.rect(mm, (50, 50, 70), (0, 0, mm_w, mm_h), 1)

    def to_mm(wx, wy):
        return (int(wx / WORLD_W * mm_w), int(wy / WORLD_H * mm_h))

    sel_ids = {id(s) for s in selected_ships}
    for ship in ai_characters:
        if not ship.alive:
            continue
        col = TEAM_COLORS[ship.team]
        if ship.team != player_team:
            col = tuple(c // 2 for c in col)
        if id(ship) in sel_ids:
            col = (255, 255, 100)
        mx2, my2 = to_mm(ship.wx + ship.width / 2, ship.wy + ship.height / 2)
        r = 3 if isinstance(ship, Carrier) else 1
        pygame.draw.circle(mm, col, (mx2, my2), r)

    # Camera viewport rect on minimap
    vp_x, vp_y = to_mm(camera.x, camera.y)
    vp_w2 = max(1, int(camera.screen_width  / WORLD_W * mm_w))
    vp_h2 = max(1, int(camera.screen_height / WORLD_H * mm_h))
    pygame.draw.rect(mm, (120, 120, 160), (vp_x, vp_y, vp_w2, vp_h2), 1)

    screen.blit(mm, (mm_x, mm_y))
    label = font_sm.render("MINIMAP", True, (80, 80, 110))
    screen.blit(label, (mm_x + 4, mm_y + mm_h + 2))

    # ── Team banner (top-centre) ───────────────────────────────────────────────
    font_banner = pygame.font.SysFont("impact", 22)
    banner_text = f"{TEAM_NAMES[player_team]}  vs  {TEAM_NAMES[enemy_team]}"
    banner_surf = font_banner.render(banner_text, True, team_col)
    bx = screen_w // 2 - banner_surf.get_width() // 2
    bg2 = pygame.Surface((banner_surf.get_width() + 20, 30), pygame.SRCALPHA)
    bg2.fill((0, 0, 0, 140))
    screen.blit(bg2,         (bx - 10, 8))
    screen.blit(banner_surf, (bx, 12))


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_W, SCREEN_H), pygame.RESIZABLE)
    pygame.display.set_caption("Space Ranters")
    clock  = pygame.time.Clock()

    # ── Menu ──────────────────────────────────────────────────────────────────
    player_team = run_menu(screen, clock)

    # ── Loading screen → world + entities built in background thread ──────────
    world_surf, ai_characters = run_loading_screen(screen, clock, player_team)
    camera = Camera(SCREEN_W, SCREEN_H)
    lasers:     list[Laser]     = []
    explosions: list[Explosion] = []

    # Start camera centred on the player team's first carrier
    own_carriers = [s for s in ai_characters
                    if isinstance(s, Carrier) and s.team == player_team]
    if own_carriers:
        c = own_carriers[0]
        camera.follow(c.wx + c.width / 2, c.wy + c.height / 2)

    # ── RTS state ─────────────────────────────────────────────────────────────
    selected_ships: list = []
    # player_orders: id(ship) → {'ship_ref', 'type': 'move'|'attack', 'pos'|'target'}
    player_orders:  dict = {}

    lmb_start  = None   # LMB press position for click / box-select
    rmb_start  = None   # RMB press position for click vs. drag detection
    rmb_drag   = False  # True once RMB has moved enough to count as a pan
    drag_orig  = (0, 0) # Last drag position for incremental pan

    elapsed = 0.0
    # Command marker positions to show (list of (wx, wy))
    cmd_markers: list = []
    cmd_marker_t = 0.0  # countdown to remove markers

    while True:
        dt        = clock.tick(FPS) / 1000.0
        elapsed  += dt
        screen_w, screen_h = screen.get_size()
        camera.screen_width  = screen_w
        camera.screen_height = screen_h
        mx, my = pygame.mouse.get_pos()

        # ── Events ────────────────────────────────────────────────────────────
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit(); sys.exit()

            # ── Keyboard ──────────────────────────────────────────────────────
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    selected_ships.clear()
                    player_orders.clear()
                    cmd_markers.clear()
                if event.key == pygame.K_a and (pygame.key.get_mods() & pygame.KMOD_CTRL):
                    selected_ships = [s for s in ai_characters
                                      if s.team == player_team and s.alive]

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
                        # Click select
                        clicked = get_ship_at(ai_characters, camera, ex, ey)
                        if clicked is None:
                            # Click on empty space — deselect unless shift held
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
                        # Clicking an enemy ship without shift just deselects
                        elif not (mods & pygame.KMOD_SHIFT):
                            selected_ships.clear()
                    else:
                        # Box select — only friendly ships
                        box = pygame.Rect(min(sx, ex), min(sy, ey),
                                          abs(ex - sx), abs(ey - sy))
                        found = get_ships_in_box(
                            [s for s in ai_characters
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
                if rmb_start is not None and not rmb_drag:
                    # Short click → issue command
                    cx_s, cy_s = rmb_start
                    target_enemy = get_ship_at(
                        [s for s in ai_characters
                         if s.team != player_team and s.alive],
                        camera, cx_s, cy_s,
                    )
                    wx, wy = camera.screen_to_world(cx_s, cy_s)
                    n = len(selected_ships)
                    cmd_markers.clear()

                    for i, ship in enumerate(selected_ships):
                        if target_enemy is not None:
                            player_orders[id(ship)] = {
                                'ship_ref': ship,
                                'type':     'attack',
                                'target':   target_enemy,
                            }
                        else:
                            # Fan the ships around the click point
                            if n > 1:
                                angle = i * (math.tau / n)
                                r     = 180 + (n // 4) * 60
                                ox    = math.cos(angle) * r
                                oy    = math.sin(angle) * r
                            else:
                                ox, oy = 0.0, 0.0
                            dest = (wx + ox, wy + oy)
                            player_orders[id(ship)] = {
                                'ship_ref': ship,
                                'type':     'move',
                                'pos':      dest,
                            }
                            cmd_markers.append(dest)

                    if target_enemy is not None:
                        # Show marker at the enemy's current position
                        tx = target_enemy.wx + target_enemy.width  / 2
                        ty = target_enemy.wy + target_enemy.height / 2
                        cmd_markers.append((tx, ty))

                    cmd_marker_t = 2.5   # show markers for 2.5 seconds

                rmb_start = None
                rmb_drag  = False

        # ── Update ────────────────────────────────────────────────────────────
        for ship in ai_characters:
            ship.update(dt)

        alive_before = {id(s): s.alive for s in ai_characters}
        for ship in ai_characters:
            ship.update_combat(dt, ai_characters, lasers)

        # Apply player orders — override combat AI's movement destination
        to_clear = []
        for ship_id, order in player_orders.items():
            ref = order['ship_ref']
            if not ref.alive:
                to_clear.append(ship_id)
                continue
            if order['type'] == 'move':
                px, py = order['pos']
                ref._movement_override = (px, py)
                cx2 = ref.wx + ref.width  / 2
                cy2 = ref.wy + ref.height / 2
                if math.hypot(cx2 - px, cy2 - py) < 200:
                    to_clear.append(ship_id)          # arrived — release the order
            elif order['type'] == 'attack':
                tgt = order['target']
                if not tgt.alive:
                    to_clear.append(ship_id)
                else:
                    tx2 = tgt.wx + tgt.width  / 2
                    ty2 = tgt.wy + tgt.height / 2
                    ref._movement_override = (tx2, ty2)   # keep chasing

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
                    angle = random.uniform(0, math.tau)
                    fighter.fleet_offset = (math.cos(angle) * 200, math.sin(angle) * 200)
                    ship._active_fighters.append(fighter)
                    new_fighters.append(fighter)
                ship._spawn_queue.clear()
        if new_fighters:
            ai_characters.extend(new_fighters)

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
        vp_w = max(1, int(screen_w / camera.zoom))
        vp_h = max(1, int(screen_h / camera.zoom))
        vp_rect = pygame.Rect(int(camera.x), int(camera.y), vp_w, vp_h)
        vp_rect = vp_rect.clip(world_surf.get_rect())
        if vp_rect.width > 0 and vp_rect.height > 0:
            region = world_surf.subsurface(vp_rect)
            pygame.transform.scale(region, (screen_w, screen_h), screen)

        for ship in ai_characters:
            ship.draw(screen, camera)

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
            draw_select_box(screen, lmb_start, (mx, my))

        draw_hud(screen, camera, ai_characters, player_team,
                 selected_ships, clock.get_fps(), screen_w, screen_h, player_orders)

        pygame.display.flip()


if __name__ == "__main__":
    main()
