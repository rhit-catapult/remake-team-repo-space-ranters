"""
CommandCenter — Defensive structure orbiting the home planet.
Destroying the opponent's command center is the primary win condition.
"""
import math
import pygame


class CommandCenter:
    """A defensive command structure orbiting the home planet.
    
    Represents the heart of each team's operation. Destroying the enemy's
    command center is the only way to win. The command center:
    - Orbits the home planet
    - Has health and can be damaged
    - Can be targeted and attacked like other entities
    - Creates an explosion when destroyed
    """

    # Team colors for rendering
    _COLORS = [(100, 150, 255), (255, 100, 100)]  # Blue, Red
    
    # Health configuration
    MAX_HP = 350
    
    def __init__(self, home_planet, orbit_radius: float, angle: float, 
                 team: int, orbit_speed: float = 0.3):
        """
        Args:
            home_planet: Planet object to orbit
            orbit_radius: Distance from planet center
            angle: Starting angle in radians
            team: 0 for Blue, 1 for Red
            orbit_speed: Angular velocity (radians per second)
        """
        self.home_planet = home_planet
        self.team = team
        self.orbit_radius = orbit_radius
        self.angle = angle
        self.orbit_speed = orbit_speed
        
        # Health & state
        self.max_hp = self.MAX_HP
        self.hp = self.max_hp
        self.alive = True
        
        # Dimensions (cubic command center)
        self.radius = 70
        self.width = self.radius * 2
        self.height = self.radius * 2
        
        # Color
        self.color = self._COLORS[team]
        self._col_dark = tuple(max(0, c - 90) for c in self.color)
        self._col_bright = tuple(min(255, c + 60) for c in self.color)
        
        # Position (updated in update())
        self.wx = 0.0
        self.wy = 0.0
        self._update_position()
    
    def _update_position(self):
        """Update orbital position based on angle."""
        self.wx = (self.home_planet.star_x + 
                   math.cos(self.angle) * self.orbit_radius - self.radius)
        self.wy = (self.home_planet.star_y + 
                   math.sin(self.angle) * self.orbit_radius - self.radius)
    
    @property
    def world_rect(self) -> pygame.Rect:
        """Return world-space bounding rect."""
        return pygame.Rect(int(self.wx), int(self.wy), self.width, self.height)
    
    def update(self, dt: float):
        """Update orbital position and rotation."""
        if not self.alive:
            return
        
        # Update orbital angle
        self.angle = (self.angle + self.orbit_speed * dt) % math.tau
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
        """Take damage with a hit chance roll. Returns True if hit.
        Command centers are larger targets, so they have a high hit chance."""
        import random
        hit_chance = 0.95  # Very hard to miss a command center
        if random.random() < hit_chance:
            self.take_damage(damage)
            return True
        return False
    
    def draw(self, surface: pygame.Surface, camera):
        """Render the command center as a rotating orbital station."""
        if not self.alive or not camera.is_visible_xywh(self.wx, self.wy, 
                                                         self.width, self.height):
            return
        
        # Center in screen space
        cx, cy = camera.world_to_screen(self.wx + self.radius, self.wy + self.radius)
        r = max(1, int(self.radius * camera.zoom))
        zoom = camera.zoom
        
        # Draw main structure (cube/station)
        # Outer octagon approximating a rotating station
        n_sides = 8
        outer_r = r
        pts = []
        for i in range(n_sides):
            a = self.angle + i * math.tau / n_sides
            px = cx + math.cos(a) * outer_r
            py = cy + math.sin(a) * outer_r
            pts.append((int(px), int(py)))
        
        # Fill and outline
        pygame.draw.polygon(surface, self._col_dark, pts)
        pygame.draw.polygon(surface, self.color, pts, max(1, int(2 * zoom)))
        
        # Inner rotating antenna/radar dish
        inner_r = r * 0.6
        for i in range(3):
            a1 = self.angle + i * math.tau / 3
            a2 = self.angle + (i + 0.5) * math.tau / 3
            x1 = cx + math.cos(a1) * inner_r
            y1 = cy + math.sin(a1) * inner_r
            x2 = cx + math.cos(a2) * inner_r
            y2 = cy + math.sin(a2) * inner_r
            pygame.draw.line(surface, self._col_bright, (x1, y1), (x2, y2), 
                           max(1, int(zoom)))
        
        # Center core
        pygame.draw.circle(surface, self._col_bright, (cx, cy), max(2, int(r * 0.3)))
        
        # Health bar when damaged
        if self.hp < self.max_hp:
            bar_w = r * 2
            bar_h = max(2, int(3 * zoom))
            bar_x = cx - bar_w // 2
            bar_y = cy - r - 12
            
            # Background (red = dead)
            pygame.draw.rect(surface, (120, 0, 0), (bar_x, bar_y, bar_w, bar_h))
            # Fill (green = health)
            fill_w = int(bar_w * self.hp / self.max_hp)
            pygame.draw.rect(surface, (0, 210, 60), (bar_x, bar_y, fill_w, bar_h))
            # Border
            pygame.draw.rect(surface, (200, 200, 200), (bar_x, bar_y, bar_w, bar_h), 1)
