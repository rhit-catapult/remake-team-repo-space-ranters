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

    def move(self, speed, angle):
        self.angle = angle
        dx = speed * math.cos((angle + 90) * math.pi / 180)
        dy = -speed * math.sin((angle + 90) * math.pi / 180)
        self.x += dx
        self.y += dy
    
