import pygame
import sys
import random
import time
import RTSunits
import math

def main():
    pygame.init()
    pygame.display.set_caption("Cool Project")
    screen = pygame.display.set_mode((640, 480), pygame.RESIZABLE)
    clock = pygame.time.Clock()
    
    # ships: 
    ship1 = RTSunits.Frigate(screen, 200, 200)
    speed = 0
    angle = 0
    turn_speed = 0

    while True:
        # controls
        for event in pygame.event.get(): # user interaction events:
            if event.type == pygame.QUIT: # quit
                sys.exit()
            elif event.type == pygame.KEYDOWN: # key down events:
                if event.key == pygame.K_w: # up
                    speed = 2
                elif event.key == pygame.K_s: # down
                    speed = -2
                elif event.key == pygame.K_a: # left
                    turn_speed = 3
                elif event.key == pygame.K_d: # right
                    turn_speed = -3
            if event.type == pygame.KEYUP: # key up events:
                if event.key in (pygame.K_w, pygame.K_s): # working on deceleration..
                    if speed > 0:
                        speed -= 0.5
                    elif speed < 0:
                        speed += 0.5

        angle = (angle + turn_speed) % 360

        # draw elements
        screen.fill((0, 0, 0))
        ship1.draw()
        ship1.move(speed, angle)
        
        # update screen:
        clock.tick(60)
        pygame.display.update()

    
main()