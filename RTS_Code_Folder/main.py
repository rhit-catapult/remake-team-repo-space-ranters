"""
main.py — Demonstrates a world-coordinate system with a camera viewport.

This script builds a large world surface, creates a player and AI agents,
and renders only the portion of the world that is visible through the camera.
The camera can either follow a chosen entity or be panned manually with the
right mouse button.

World size:  3200 × 2400  (much larger than the screen)
Screen size:  960 × 640

Controls:
  WASD / Arrow keys  — move the player
  F                  — toggle camera: follow player vs. free pan
  Tab                — cycle camera focus (player / AI character 1 / AI character 2)
  Mouse drag (RMB)   — pan the camera freely
  Escape             — quit
"""

import sys
import math
import random
import pygame
from camera import Camera
from entities import Player, AICharacter, Laser, Explosion, Fighter, Carrier, Destroyer

# Screen size in pixels: this is the visible display window.
SCREEN_W, SCREEN_H = 1000, 800

# World size in world-space units: this is larger than the screen so the camera
# must move to reveal different parts of the environment.

map_scale_factor = 4
WORLD_W, WORLD_H  = 4000 * map_scale_factor, 3200 * map_scale_factor

# Target frame rate for the main loop.
FPS = 60

# Number of AI characters to spawn on the map. 10000 is the limit before performace starts declining
NUM_AI = 100

# Zoom limits and scroll step (each mouse-wheel tick multiplies/divides by ZOOM_STEP).
ZOOM_MIN  = 0.15
ZOOM_MAX  = 4.0
ZOOM_STEP = 1.2

# Colours used for the world background, and HUD overlays.
BG_DARK  = (0, 0, 0)
HUD_BG   = (0, 0, 0, 160)


# ── World background ───────────────────────────────────────────────────────────
def tile_image_across_world(surf: pygame.Surface, image_path: str, world_width: int, 
                            world_height: int) -> None:
    """Tile an image across the entire world surface at its native resolution.
    
    Args:
        surf: The world surface to tile onto.
        image_path: Path to the image file to tile.
        world_width: Width of the world in pixels.
        world_height: Height of the world in pixels.
    
    The image is tiled at its original size without scaling. If the image is larger
    than a single tile position, it will extend beyond that position (but only the
    viewport rectangle is visible, so this is handled correctly).
    """
    try:
        # Load the tile image at its native resolution (no scaling)
        tile_image = pygame.image.load(image_path)
        tile_w, tile_h = tile_image.get_size()
        
        # Calculate how many tiles we need in each direction
        tiles_x = (world_width + tile_w - 1) // tile_w  # Ceiling division
        tiles_y = (world_height + tile_h - 1) // tile_h
        
        # Tile the image across the entire world
        for y in range(tiles_y):
            for x in range(tiles_x):
                tile_x = x * tile_w
                tile_y = y * tile_h
                surf.blit(tile_image, (tile_x, tile_y))
    except pygame.error as e:
        print(f"Warning: Could not load tile image '{image_path}': {e}")
        # Fall back to dark background if image fails to load
        surf.fill(BG_DARK)


def build_world_surface() -> pygame.Surface:
    """Pre-render the static world background once.

    The entire world is drawn to a single off-screen surface. During each frame,
    only the camera's visible rectangle is blitted from this surface to the
    display surface, which saves CPU and simplifies coordinate handling.
    
    The background is tiled from the RTS Background.png image at its native resolution,
    automatically accounting for variable screen and world sizes.
    """
    surf = pygame.Surface((WORLD_W, WORLD_H))
    surf.fill(BG_DARK)  # Fill with dark background as fallback.
    
    # Tile the background image across the entire world
    import os
    image_path = os.path.join(os.path.dirname(__file__), "RTS Background 2.png")
    tile_image_across_world(surf, image_path, WORLD_W, WORLD_H)
    
    return surf


# ── HUD overlay ───────────────────────────────────────────────────────────────
def draw_hud(screen: pygame.Surface, camera: Camera, entities: list,
             follow_mode: bool, focus_idx: int, fps: float,
             screen_w: int = None, screen_h: int = None):
    """Render the heads-up display and minimap over the main game view."""
    if screen_w is None:
        screen_w = screen.get_width()
    if screen_h is None:
        screen_h = screen.get_height()

    font_sm = pygame.font.SysFont("monospace", 14)

    # Lines of text that show current performance and control hints.
    lines = [
        f"FPS: {fps:.0f}",
        f"Camera world pos: ({camera.x:.0f}, {camera.y:.0f})",
        f"Zoom: {camera.zoom:.2f}x",
        f"Follow mode: {'ON' if follow_mode else 'OFF (RMB drag)'}",
        f"Focus: {'Player' if focus_idx == 0 else f'AI-{focus_idx}'}",
        "",
        "WASD/Arrows = move player",
        "Scroll wheel = zoom in/out",
        "F = toggle follow   Tab = cycle focus",
        "RMB drag = free pan",
    ]

    # Create a transparent HUD panel and draw each line of text.
    hud = pygame.Surface((260, len(lines) * 18 + 12), pygame.SRCALPHA)
    hud.fill((0, 0, 0, 150))
    for i, line in enumerate(lines):
        colour = (180, 220, 255) if i < 4 else (140, 140, 140)
        hud.blit(font_sm.render(line, True, colour), (8, 6 + i * 18))
    screen.blit(hud, (8, 8))

    # Minimap overlay shows the full world in miniature and highlights the
    # current camera viewport and entity positions.
    mm_w, mm_h = 160, 100
    mm_x, mm_y = screen_w - mm_w - 10, 10
    mm = pygame.Surface((mm_w, mm_h), pygame.SRCALPHA)
    mm.fill((0, 0, 0, 160))
    pygame.draw.rect(mm, (60, 60, 80), (0, 0, mm_w, mm_h), 1)

    def to_mm(wx, wy):
        # Convert world coordinates into minimap coordinates by scaling.
        return (int(wx / WORLD_W * mm_w), int(wy / WORLD_H * mm_h))

    # Draw the camera viewport rectangle onto the minimap.
    vp_x, vp_y = to_mm(camera.x, camera.y)
    vp_w = int(camera.screen_width / WORLD_W * mm_w)
    vp_h = int(camera.screen_height / WORLD_H * mm_h)
    pygame.draw.rect(mm, (80, 80, 120), (vp_x, vp_y, vp_w, vp_h))
    pygame.draw.rect(mm, (160, 160, 200), (vp_x, vp_y, vp_w, vp_h), 1)

    # Draw dots for each entity on the minimap: player = white, teams = blue/red.
    for i, ent in enumerate(entities):
        if i == 0:
            col = (255, 255, 255)
        elif hasattr(ent, 'alive') and not ent.alive:
            continue
        elif hasattr(ent, 'team'):
            col = (80, 140, 255) if ent.team == 0 else (255, 60, 60)
        else:
            col = (180, 180, 180)
        mx, my = to_mm(ent.wx, ent.wy)
        pygame.draw.circle(mm, col, (mx, my), 2)

    screen.blit(mm, (mm_x, mm_y))
    font_sm2 = pygame.font.SysFont("monospace", 11)
    screen.blit(font_sm2.render("MINIMAP", True, (140, 140, 160)), (mm_x + 4, mm_y + mm_h + 2))


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    """Initialize the game, create objects, and run the main update/draw loop."""
    pygame.init()  # Initialize all imported pygame modules.
    screen = pygame.display.set_mode((SCREEN_W, SCREEN_H), pygame.RESIZABLE)
    pygame.display.set_caption("World Coordinate System Demo")
    clock = pygame.time.Clock()  # Clock to manage timing and FPS.

    world_surf = build_world_surface()  # Create the static world image once.
    camera = Camera(SCREEN_W, SCREEN_H)  # Camera manages viewport position.

    player = Player(400 + 100, 300 + 80)  # Player start position in world space.

    # Generate AI characters split evenly into two teams.
    # Each team gets NUM_CARRIERS_PER_TEAM carriers; the rest are regular ships.
    NUM_CARRIERS_PER_TEAM = max(1, NUM_AI // 25)

    def _make_waypoints():
        return [(random.randint(200, WORLD_W - 200), random.randint(200, WORLD_H - 200))
                for _ in range(5)]

    NUM_DESTROYERS_PER_TEAM = 2

    ai_characters = []
    for i in range(NUM_AI):
        team = 0 if i < NUM_AI // 2 else 1
        # The first NUM_CARRIERS_PER_TEAM ships on each team are carriers
        team_slot = i if team == 0 else i - NUM_AI // 2
        wp = _make_waypoints()
        if team_slot < NUM_CARRIERS_PER_TEAM:
            ai_characters.append(Carrier(wp[0][0], wp[0][1], wp, team=team))
        else:
            ai_characters.append(AICharacter(wp[0][0], wp[0][1], wp, team=team))

    for team in (0, 1):
        team_carriers = [s for s in ai_characters if isinstance(s, Carrier) and s.team == team]
        for i in range(NUM_DESTROYERS_PER_TEAM):
            wp = _make_waypoints()
            d = Destroyer(wp[0][0], wp[0][1], wp, team=team)
            if team_carriers:
                leader = team_carriers[i % len(team_carriers)]
                d.fleet_leader     = leader
                d.fleet_offset     = (0.0, (1 if i % 2 == 0 else -1) * 550.0)
                d.fleet_stray_dist = 900.0
            ai_characters.append(d)

    # Group ships into fleets centred on each carrier (one fleet per carrier per team).
    # The first ESCORTS_PER_FLEET non-carrier ships per fleet become close escorts —
    # tight formation, short leash, always engage directly.  The rest fan out further.
    ESCORTS_PER_FLEET = 3
    for team in (0, 1):
        carriers  = [s for s in ai_characters if isinstance(s, Carrier) and s.team == team]
        non_carry = [s for s in ai_characters if not isinstance(s, Carrier) and s.team == team]
        if not carriers:
            continue
        for carrier in carriers:
            carrier.fleet_leader = carrier
        for i, ship in enumerate(non_carry):
            leader     = carriers[i % len(carriers)]
            fleet_slot = i // len(carriers)   # position index within that fleet
            ship.fleet_leader = leader
            if fleet_slot < ESCORTS_PER_FLEET:
                # Close escort: tight ring around the carrier, short leash
                angle  = fleet_slot * (math.tau / ESCORTS_PER_FLEET)
                radius = 260
                ship.fleet_stray_dist = 380
                ship.role = 'attacker'   # escorts charge; never flank away from the carrier
            else:
                # Regular fleet member: loose golden-angle spread
                slot   = fleet_slot - ESCORTS_PER_FLEET
                angle  = slot * 2.39996   # golden angle in radians (~137.5°)
                radius = 300 + (slot % 4) * 130
                # fleet_stray_dist stays at the default (900)
            ship.fleet_offset = (math.cos(angle) * radius, math.sin(angle) * radius)

    lasers:     list[Laser]     = []
    explosions: list[Explosion] = []

    entities = [player] + ai_characters  # All world entities updated and drawn each frame.

    follow_mode = True  # Whether the camera should track the selected focus entity.
    focus_idx   = 0     # Index of the current camera focus: 0=player, 1=ai1, 2=ai2.
    dragging    = False  # Whether the right mouse button is currently dragging.
    drag_origin = (0, 0)  # Last mouse position used for dragging calculations.

    camera.follow(player.wx, player.wy)  # Snap camera to the player's start position.

    while True:
        dt = clock.tick(FPS) / 1000.0  # Delta time in seconds, used for consistent motion.

        # ── Events ─────────────────────────────────────────────────────
        # Handle all user input and window events before updating game state.
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit(); sys.exit()

            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    pygame.quit(); sys.exit()
                if event.key == pygame.K_f:
                    follow_mode = not follow_mode  # Toggle automatic camera following.
                if event.key == pygame.K_TAB:
                    focus_idx = (focus_idx + 1) % len(entities)  # Cycle camera focus.

            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 3:
                dragging = True
                drag_origin = event.pos  # Start dragging from the current mouse pos.

            if event.type == pygame.MOUSEBUTTONUP and event.button == 3:
                dragging = False  # Stop panning when the right mouse button is released.

            if event.type == pygame.MOUSEMOTION and dragging:
                dx = drag_origin[0] - event.pos[0]
                dy = drag_origin[1] - event.pos[1]
                # Divide by zoom so one screen-pixel drag = one world-unit pan at any zoom.
                camera.move(dx / camera.zoom, dy / camera.zoom)
                drag_origin = event.pos
                follow_mode = False  # Break follow mode when user manually pans.

            if event.type == pygame.MOUSEWHEEL:
                mx, my = pygame.mouse.get_pos()
                if event.y > 0:
                    new_zoom = min(camera.zoom * ZOOM_STEP, ZOOM_MAX)
                else:
                    new_zoom = max(camera.zoom / ZOOM_STEP, ZOOM_MIN)
                camera.zoom_toward(new_zoom, mx, my)

        # ── Update ─────────────────────────────────────────────────────
        for ent in entities:
            ent.update(dt)

        # Keep the player inside the limits of the world.
        player.wx = max(0, min(player.wx, WORLD_W - player.width))
        player.wy = max(0, min(player.wy, WORLD_H - player.height))

        # Laser combat: fire beams, apply damage instantly, track kills for explosions.
        alive_before = {id(s): s.alive for s in ai_characters}
        for ship in ai_characters:
            ship.update_combat(dt, ai_characters, lasers)
        for ship in ai_characters:
            if alive_before.get(id(ship)) and not ship.alive:
                explosions.append(Explosion(
                    ship.wx + ship.width  / 2,
                    ship.wy + ship.height / 2,
                    ship.width, ship.height,
                ))

        # Process carrier spawn queues — add new fighters to the game.
        new_fighters = []
        for ship in ai_characters:
            if isinstance(ship, Carrier) and ship._spawn_queue:
                for fx, fy, fteam in ship._spawn_queue:
                    wp = [(random.randint(200, WORLD_W - 200), random.randint(200, WORLD_H - 200))
                          for _ in range(5)]
                    fighter = Fighter(fx, fy, wp, fteam, home_carrier=ship)
                    fighter.fleet_leader = ship
                    angle = random.uniform(0, math.tau)
                    fighter.fleet_offset = (math.cos(angle) * 200, math.sin(angle) * 200)
                    ship._active_fighters.append(fighter)
                    new_fighters.append(fighter)
                ship._spawn_queue.clear()
        if new_fighters:
            ai_characters.extend(new_fighters)
            entities.extend(new_fighters)

        # Fade and prune laser visuals (damage was applied at fire time).
        for laser in lasers:
            laser.update(dt)
        lasers[:] = [l for l in lasers if l.alive]

        # Update and prune finished explosions.
        for exp in explosions:
            exp.update(dt)
        explosions[:] = [e for e in explosions if e.alive]

        # If camera follow is enabled, smoothly move the camera toward the focus entity.
        if follow_mode:
            focus = entities[focus_idx]
            camera.follow(
                focus.wx + focus.width  / 2,
                focus.wy + focus.height / 2,
                lerp=0.08,   # Smooth interpolation factor; smaller values are slower.
            )
        camera.clamp(WORLD_W, WORLD_H)  # Prevent camera from leaving the world.

        # ── Draw ───────────────────────────────────────────────────────
        # Sync camera dimensions in case the window was resized.
        screen_w, screen_h = screen.get_size()
        camera.screen_width  = screen_w
        camera.screen_height = screen_h

        # Draw the world: extract the viewport region in world space then scale to screen.
        vp_w = max(1, int(screen_w / camera.zoom))
        vp_h = max(1, int(screen_h / camera.zoom))
        vp_rect = pygame.Rect(int(camera.x), int(camera.y), vp_w, vp_h)
        vp_rect = vp_rect.clip(world_surf.get_rect())  # stay within world bounds
        if vp_rect.width > 0 and vp_rect.height > 0:
            region = world_surf.subsurface(vp_rect)
            pygame.transform.scale(region, (screen_w, screen_h), screen)

        # Draw all entities on the screen using the camera for coordinate translation.
        for ent in entities:
            ent.draw(screen, camera)

        # Draw laser beams on top of ships.
        for laser in lasers:
            laser.draw(screen, camera)

        # Draw explosions on top of everything.
        for exp in explosions:
            exp.draw(screen, camera)

        # Draw HUD and minimap overlays after world and entity rendering.
        draw_hud(screen, camera, entities, follow_mode, focus_idx, clock.get_fps(), screen_w, screen_h)

        pygame.display.flip()  # Present the rendered frame to the display.


if __name__ == "__main__":
    main()