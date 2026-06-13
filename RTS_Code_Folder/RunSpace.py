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
    forward_speed = 0
    strafe_speed = 0
    angle = 0
    turn_speed = 0
    lasers = []
    
    # Deceleration settings (space physics simulation)
    deceleration = 0.90  # Speed retains 90% per frame (10% reduction)
    strafe_deceleration = 0.90
    turn_deceleration = 0.95  # Rotation has slightly more drag
    reversal_threshold = 0.5  # Speed must be near zero before reversing direction
    laser_speed = 12
    laser_color = (0, 255, 255)
    laser_radius = 3

    while True:
        # controls
        for event in pygame.event.get(): # user interaction events:
            if event.type == pygame.QUIT: # quit
                sys.exit()
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_f:
                    front_x, front_y = ship1.get_front_position()
                    lasers.append({
                        'x': front_x,
                        'y': front_y,
                        'angle': angle,
                        'speed': laser_speed,
                    })
        
        # Check for held keys (allows continuous input)
        keys = pygame.key.get_pressed()
        
        # Reset acceleration inputs each frame
        forward_input = 0
        strafe_input = 0
        turn_input = 0
        
        forward_input_speed = 2
        strafe_input_speed = 2
        turn_input_speed = 1.5

        if keys[pygame.K_w]:
            forward_input = forward_input_speed
        if keys[pygame.K_s]:
            forward_input = -forward_input_speed
        
        if keys[pygame.K_a]:
            strafe_input = -strafe_input_speed
        if keys[pygame.K_d]:
            strafe_input = strafe_input_speed
        
        if keys[pygame.K_q]:
            turn_input = turn_input_speed
        if keys[pygame.K_e]:
            turn_input = -turn_input_speed
        
        # Apply forward/backward momentum
        if forward_input != 0:
            if (forward_input > 0 and forward_speed >= -reversal_threshold) or (forward_input < 0 and forward_speed <= reversal_threshold):
                forward_speed = forward_input
            else:
                forward_speed *= deceleration
        else:
            forward_speed *= deceleration
        
        # Apply strafing momentum
        if strafe_input != 0:
            if (strafe_input > 0 and strafe_speed >= -reversal_threshold) or (strafe_input < 0 and strafe_speed <= reversal_threshold):
                strafe_speed = strafe_input
            else:
                strafe_speed *= strafe_deceleration
        else:
            strafe_speed *= strafe_deceleration
        
        # Apply rotation momentum
        if turn_input != 0:
            if (turn_input > 0 and turn_speed >= -reversal_threshold) or (turn_input < 0 and turn_speed <= reversal_threshold):
                turn_speed = turn_input
            else:
                turn_speed *= turn_deceleration
        else:
            turn_speed *= turn_deceleration
        
        # Stop very small velocities to prevent drift
        if abs(forward_speed) < 0.01:
            forward_speed = 0
        if abs(strafe_speed) < 0.01:
            strafe_speed = 0
        if abs(turn_speed) < 0.01:
            turn_speed = 0

        angle = (angle + turn_speed) % 360

        # draw elements
        screen.fill((0, 0, 0))
        ship1.draw()
        ship1.move(forward_speed, strafe_speed, angle)

        # Update and draw lasers
        for laser in lasers[:]:
            dx = laser['speed'] * math.cos((laser['angle'] + 90) * math.pi / 180)
            dy = -laser['speed'] * math.sin((laser['angle'] + 90) * math.pi / 180)
            laser['x'] += dx
            laser['y'] += dy
            pygame.draw.circle(screen, laser_color, (int(laser['x']), int(laser['y'])), laser_radius)
            if laser['x'] < 0 or laser['x'] > screen.get_width() or laser['y'] < 0 or laser['y'] > screen.get_height():
                lasers.remove(laser)
        
        # update screen:
        clock.tick(60)
        pygame.display.update()

    
main()