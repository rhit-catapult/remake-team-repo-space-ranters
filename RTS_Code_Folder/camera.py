"""
camera.py — Translates between world space and screen space.
"""
import pygame


class Camera:
    """
    Tracks a position in world space and converts world coordinates
    to screen coordinates (and vice versa) for rendering.
    """

    def __init__(self, screen_width: int, screen_height: int):
        self.screen_width = screen_width
        self.screen_height = screen_height
        # Camera position = top-left corner of the viewport in world space
        self.x: float = 0.0
        self.y: float = 0.0

    # ------------------------------------------------------------------
    # Coordinate conversion
    # ------------------------------------------------------------------

    def world_to_screen(self, wx: float, wy: float) -> tuple[int, int]:
        """Convert a world position to screen pixels."""
        return (int(wx - self.x), int(wy - self.y))

    def screen_to_world(self, sx: int, sy: int) -> tuple[float, float]:
        """Convert screen pixels back to world coordinates."""
        return (sx + self.x, sy + self.y)

    def world_rect_to_screen(self, world_rect: pygame.Rect) -> pygame.Rect:
        """Offset a pygame.Rect from world space to screen space."""
        sx, sy = self.world_to_screen(world_rect.x, world_rect.y)
        return pygame.Rect(sx, sy, world_rect.width, world_rect.height)

    def is_visible(self, world_rect: pygame.Rect) -> bool:
        """Return True if any part of world_rect is within the viewport."""
        screen_rect = self.world_rect_to_screen(world_rect)
        viewport = pygame.Rect(0, 0, self.screen_width, self.screen_height)
        return viewport.colliderect(screen_rect)

    # ------------------------------------------------------------------
    # Camera movement
    # ------------------------------------------------------------------

    def follow(self, target_wx: float, target_wy: float, lerp: float = 1.0):
        """
        Move the camera so the target is centred on screen.
        lerp=1.0 → instant snap; 0 < lerp < 1 → smooth follow.
        """
        desired_x = target_wx - self.screen_width / 2
        desired_y = target_wy - self.screen_height / 2
        self.x += (desired_x - self.x) * lerp
        self.y += (desired_y - self.y) * lerp

    def move(self, dx: float, dy: float):
        """Pan the camera by a delta in world units."""
        self.x += dx
        self.y += dy

    def clamp(self, world_width: int, world_height: int):
        """Prevent the camera from showing outside a bounded world."""
        self.x = max(0, min(self.x, world_width - self.screen_width))
        self.y = max(0, min(self.y, world_height - self.screen_height))