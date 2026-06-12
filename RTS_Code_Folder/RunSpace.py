import pygame
import sys
import random
import time
import RTSunits

def main():
    pygame.init()
    pygame.display.set_caption("Cool Project")
    screen = pygame.display.set_mode((640, 480), pygame.RESIZABLE)
    clock = pygame.time.Clock()
    
    # ships: 

    while True:
        clock.tick(60)  # this sets the framerate of your game
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                sys.exit()

            # TODO: keyboard events here:

        screen.fill((255, 255, 255))

        # TODO: project code:

        # update screen:
        clock.tick(60)
        pygame.display.update()


main()