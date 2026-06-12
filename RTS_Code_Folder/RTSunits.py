import pygame
import sys
import random
import time

class Frigate:
    def __init__(self, screen, x, y, dx, dy):
        self.screen = screen
        self.x, self.y = x, y
        self.dx, self.dy = dx, dy
    
    def move(self, speed):
        pass
