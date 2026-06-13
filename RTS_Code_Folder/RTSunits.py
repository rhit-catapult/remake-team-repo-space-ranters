import pygame
import sys
import random
import time
import math

class Frigate:
    def __init__(self, screen, x, y):
        self.screen = screen
        self.image = pygame.image.load("RTS_Code_Folder\\Friget_V1.png").convert_alpha()
        self.x, self.y = x, y
        self.angle = 0

    def draw(self):
        rotated = pygame.transform.rotate(self.image, self.angle)
        rotated_rect = rotated.get_rect(center=(self.x, self.y))
        self.screen.blit(rotated, rotated_rect)

    def move(self, forward_speed, strafe_speed, angle):
        self.angle = angle
        # Forward/backward motion along the ship's facing direction
        dx = forward_speed * math.cos((angle + 90) * math.pi / 180)
        dy = -forward_speed * math.sin((angle + 90) * math.pi / 180)
        # Strafing motion perpendicular to facing direction
        dx += strafe_speed * math.cos(angle * math.pi / 180)
        dy += -strafe_speed * math.sin(angle * math.pi / 180)
        self.x += dx
        self.y += dy

    def get_front_position(self):
        # approximate front of the ship at a distance of half the image height
        offset = self.image.get_height() / 2
        front_x = self.x + offset * math.cos((self.angle + 90) * math.pi / 180)
        front_y = self.y - offset * math.sin((self.angle + 90) * math.pi / 180)
        return front_x, front_y
    
