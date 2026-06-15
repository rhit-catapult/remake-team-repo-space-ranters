"""
camera.py — Translates between world space and screen space with zoom support.
"""
import pygame


class Camera:
    """
    Tracks a position in world space and converts world coordinates
    to screen coordinates (and vice versa) for rendering.

    zoom > 1  → zoomed in  (fewer world units visible)
    zoom < 1  → zoomed out (more world units visible)
    """

    def __init__(self, screen_width: int, screen_height: int):
        self.screen_width  = screen_width
        self.screen_height = screen_height
        # Top-left corner of the viewport in world space
        self.x: float    = 0.0
        self.y: float    = 0.0
        self.zoom: float = 1.0

    # ── Coordinate conversion ─────────────────────────────────────────────────

    def world_to_screen(self, wx: float, wy: float) -> tuple[int, int]:
        """Convert a world position to screen pixels."""
        return (int((wx - self.x) * self.zoom),
                int((wy - self.y) * self.zoom))

    def screen_to_world(self, sx: int, sy: int) -> tuple[float, float]:
        """Convert screen pixels back to world coordinates."""
        return (sx / self.zoom + self.x,
                sy / self.zoom + self.y)

    def world_rect_to_screen(self, world_rect: pygame.Rect) -> pygame.Rect:
        """Scale and offset a pygame.Rect from world space to screen space."""
        sx, sy = self.world_to_screen(world_rect.x, world_rect.y)
        return pygame.Rect(sx, sy,
                           int(world_rect.width  * self.zoom),
                           int(world_rect.height * self.zoom))

    def is_visible(self, world_rect: pygame.Rect) -> bool:
        """Return True if any part of world_rect is within the viewport."""
        screen_rect = self.world_rect_to_screen(world_rect)
        viewport    = pygame.Rect(0, 0, self.screen_width, self.screen_height)
        return viewport.colliderect(screen_rect)

    # ── Viewport dimensions in world space ───────────────────────────────────

    @property
    def view_width(self) -> float:
        """World units visible horizontally at the current zoom."""
        return self.screen_width / self.zoom

    @property
    def view_height(self) -> float:
        """World units visible vertically at the current zoom."""
        return self.screen_height / self.zoom

    # ── Camera movement ───────────────────────────────────────────────────────

    def follow(self, target_wx: float, target_wy: float, lerp: float = 1.0):
        """
        Move the camera so the target is centred on screen.
        lerp=1.0 → instant snap; 0 < lerp < 1 → smooth follow.
        """
        desired_x = target_wx - self.view_width  / 2
        desired_y = target_wy - self.view_height / 2
        self.x += (desired_x - self.x) * lerp
        self.y += (desired_y - self.y) * lerp

    def move(self, dx: float, dy: float):
        """Pan the camera by a delta in world units."""
        self.x += dx
        self.y += dy

    def zoom_toward(self, new_zoom: float, screen_px: int, screen_py: int):
        """
        Set a new zoom level while keeping the world point under
        (screen_px, screen_py) fixed on screen.
        """
        # World point currently under the cursor
        wx = screen_px / self.zoom + self.x
        wy = screen_py / self.zoom + self.y
        self.zoom = new_zoom
        # Reposition so that same world point is still under the cursor
        self.x = wx - screen_px / self.zoom
        self.y = wy - screen_py / self.zoom

    def clamp(self, world_width: int, world_height: int):
        """Prevent the camera from showing outside the bounded world."""
        self.x = max(0.0, min(self.x, world_width  - self.view_width))
        self.y = max(0.0, min(self.y, world_height - self.view_height))
