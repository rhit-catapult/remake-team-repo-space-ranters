"""
entity.py — Game objects that exist in world space.
All positions are world coordinates; the camera handles rendering.
"""
import math
import pygame


class Entity:
    """Base class. Lives in world space; knows nothing about the screen."""

    def __init__(self, wx: float, wy: float, width: int, height: int, color):
        self.wx = wx          # world x
        self.wy = wy          # world y
        self.width = width
        self.height = height
        self.color = color

    @property
    def world_rect(self) -> pygame.Rect:
        return pygame.Rect(int(self.wx), int(self.wy), self.width, self.height)

    def update(self, dt: float):
        pass  # override in subclasses

    def draw(self, surface: pygame.Surface, camera):
        """Draw only if inside the camera's viewport."""
        if camera.is_visible(self.world_rect):
            screen_rect = camera.world_rect_to_screen(self.world_rect)
            pygame.draw.rect(surface, self.color, screen_rect)


class Player(Entity):
    """Player-controlled entity."""

    SPEED = 200  # world units per second

    def __init__(self, wx: float, wy: float):
        super().__init__(wx, wy, 32, 32, (80, 180, 255))

    def update(self, dt: float):
        keys = pygame.key.get_pressed()
        dx = (keys[pygame.K_d] or keys[pygame.K_RIGHT]) - (keys[pygame.K_a] or keys[pygame.K_LEFT])
        dy = (keys[pygame.K_s] or keys[pygame.K_DOWN]) - (keys[pygame.K_w] or keys[pygame.K_UP])
        if dx and dy:   # normalise diagonal movement
            dx *= 0.7071
            dy *= 0.7071
        self.wx += dx * self.SPEED * dt
        self.wy += dy * self.SPEED * dt

    def draw(self, surface, camera):
        super().draw(surface, camera)
        # Draw a direction indicator dot
        if camera.is_visible(self.world_rect):
            cx, cy = camera.world_to_screen(self.wx + self.width / 2, self.wy + self.height / 2)
            pygame.draw.circle(surface, (255, 255, 255), (cx, cy), 5)


class AICharacter(Entity):
    """
    Moves between waypoints entirely in world space —
    even when off screen. This is the key demonstration:
    the character keeps moving whether or not the camera is watching.
    """

    SPEED = 80  # world units per second

    def __init__(self, wx: float, wy: float, waypoints: list[tuple[float, float]]):
        super().__init__(wx, wy, 28, 28, (255, 140, 60))
        self.waypoints = waypoints
        self.current_wp = 0

    @property
    def target(self) -> tuple[float, float]:
        return self.waypoints[self.current_wp]

    def update(self, dt: float):
        tx, ty = self.target
        dx = tx - self.wx
        dy = ty - self.wy
        dist = math.hypot(dx, dy)
        if dist < 4:
            # Reached waypoint — advance to next
            self.current_wp = (self.current_wp + 1) % len(self.waypoints)
        else:
            self.wx += (dx / dist) * self.SPEED * dt
            self.wy += (dy / dist) * self.SPEED * dt

    def draw(self, surface, camera):
        super().draw(surface, camera)
        # Draw a small triangle pointing toward next waypoint
        if camera.is_visible(self.world_rect):
            tx, ty = self.target
            cx = self.wx + self.width / 2
            cy = self.wy + self.height / 2
            angle = math.atan2(ty - cy, tx - cx)
            tip_wx = cx + math.cos(angle) * 20
            tip_wy = cy + math.sin(angle) * 20
            tip_sx = camera.world_to_screen(tip_wx, tip_wy)
            centre_sx = camera.world_to_screen(cx, cy)
            pygame.draw.line(surface, (255, 220, 100), centre_sx, tip_sx, 2)