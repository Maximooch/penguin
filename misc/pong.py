# This is a simple Pong game implementation using pygame.
# It includes basic game mechanics like paddle movement, ball physics, scoring, and sound effects.
# The game supports different modes (player vs AI, player vs player, AI vs AI) and difficulty levels.
# It also includes power-ups that can be collected by the player to gain temporary advantages.

# TODO: Take care of stuttering framerate.
# TODO: esc should go back to main menu. Not quit game.
# TODO: Add a "pause" state.
# TODO: Add a "restart" state.
# TODO: Add a "quit" state.
# TODO: Add a "settings" state.
# TODO: Add a "credits" state.
# TODO: Add a "high scores" state.

# Maybe make ball a penguin object.

import pygame # type: ignore
import sys
import random
import time
import math

# Initialize pygame
pygame.init()
pygame.mixer.init()  # Initialize the mixer for sound effects

# Load sound effects
try:
    paddle_sound = pygame.mixer.Sound('paddle_hit.wav')
    score_sound = pygame.mixer.Sound('score.wav')
    wall_sound = pygame.mixer.Sound('wall_hit.wav')
except:
    # Create placeholder sound objects if files aren't found
    paddle_sound = pygame.mixer.Sound(pygame.mixer.Sound.from_buffer(bytes([0]*44)))
    score_sound = pygame.mixer.Sound(pygame.mixer.Sound.from_buffer(bytes([0]*44)))
    wall_sound = pygame.mixer.Sound(pygame.mixer.Sound.from_buffer(bytes([0]*44)))
    
    # Print message indicating need for sound files
    print("Sound files not found. Place 'paddle_hit.wav', 'score.wav', and 'wall_hit.wav' in the same directory for sound effects.")

# Constants
WIDTH, HEIGHT = 800, 600
# Power-up constants
POWERUP_SIZE = 20
POWERUP_DURATION = 5  # seconds
POWERUP_TYPES = ["speed", "size", "slow"]
POWERUP_COLORS = {"speed": (255, 255, 0), "size": (0, 255, 0), "slow": (0, 255, 255)}
PADDLE_WIDTH, PADDLE_HEIGHT = 15, 100
BALL_SIZE = 15
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
FPS = 60

# Create the game window
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_icon(pygame.Surface((32, 32)))  # Simple icon
pygame.display.set_caption("Pong Game")
clock = pygame.time.Clock()

# Font for displaying score
font = pygame.font.Font(None, 74)

class Paddle:
    def __init__(self, x, y):
        self.rect = pygame.Rect(x, y, PADDLE_WIDTH, PADDLE_HEIGHT)
        self.speed = 7
        self.score = 0
    
    def move(self, up=True):
        if up:
            self.rect.y -= self.speed
        else:
            self.rect.y += self.speed
        
        # Keep paddle on screen
        if self.rect.top < 0:
            self.rect.top = 0
        if self.rect.bottom > HEIGHT:
            self.rect.bottom = HEIGHT
    
    def draw(self):
        pygame.draw.rect(screen, WHITE, self.rect)

class PowerUp:
    def __init__(self, power_type):
        self.type = power_type
        self.color = POWERUP_COLORS[power_type]
        # Random position (not too close to edges)
        self.rect = pygame.Rect(
            random.randint(100, WIDTH - 100),
            random.randint(100, HEIGHT - 100),
            POWERUP_SIZE, POWERUP_SIZE
        )
        self.active = True
        self.start_time = None
        self.is_applied = False
        
    def draw(self):
        if self.active:
            pygame.draw.rect(screen, self.color, self.rect)
            
            # Add a simple pulsing effect
            size_offset = math.sin(time.time() * 5) * 5
            pulse_rect = pygame.Rect(
                self.rect.x - size_offset/2,
                self.rect.y - size_offset/2,
                self.rect.width + size_offset,
                self.rect.height + size_offset
            )
            pygame.draw.rect(screen, self.color, pulse_rect, 1)
            
            # Draw icon or letter based on type
            font = pygame.font.Font(None, 20)
            icon = font.render(self.type[0].upper(), True, BLACK)
            screen.blit(icon, (self.rect.x + 6, self.rect.y + 4))
    
    def apply_effect(self, player1, player2, ball):
        if not self.is_applied:
            self.start_time = time.time()
            self.is_applied = True
            
            if self.type == "speed":
                # Speed up player
                player1.speed = 12
            elif self.type == "size":
                # Increase paddle size
                player1.rect.height = int(PADDLE_HEIGHT * 1.5)
                # Reposition to maintain center
                player1.rect.y -= PADDLE_HEIGHT // 4
            elif self.type == "slow":
                # Slow down AI
                player2.speed = 3
    
    def remove_effect(self, player1, player2, ball):
        if self.is_applied:
            if self.type == "speed":
                # Reset player speed
                player1.speed = 7
            elif self.type == "size":
                # Reset paddle size
                player1.rect.height = PADDLE_HEIGHT
            elif self.type == "slow":
                # Reset AI speed
                player2.speed = 5 + player2.game.difficulty_level

class Ball:
    def __init__(self, mode="player_vs_ai", difficulty=1):
        self.rect = pygame.Rect(WIDTH // 2 - BALL_SIZE // 2, 
                              HEIGHT // 2 - BALL_SIZE // 2,
                              BALL_SIZE, BALL_SIZE)
        self.speed_x = 7 * random.choice((1, -1))
        self.speed_y = 7 * random.choice((1, -1))
        self.active = False
        self.last_hit = None
    
    def move(self):
        if not self.active:
            return
            
        self.rect.x += self.speed_x
        self.rect.y += self.speed_y
        
        # Bounce off top and bottom
        if self.rect.top <= 0 or self.rect.bottom >= HEIGHT:
            self.speed_y *= -1
            
            # Add slight randomization to prevent "stuck" horizontal trajectories
            self.speed_y += random.uniform(-0.5, 0.5)
            
            # Ensure horizontal speed is never too small
            if abs(self.speed_x) < 2:
                self.speed_x = 2 * (1 if self.speed_x > 0 else -1)
                
            wall_sound.play()
        
    def reset(self, difficulty=1):
        self.rect.center = (WIDTH // 2, HEIGHT // 2)
        base_speed = 5 + difficulty
        self.speed_x = base_speed * random.choice((1, -1))
        self.speed_y = base_speed * random.choice((1, -1))
        self.active = False
        self.last_hit = None
    
    def draw(self):
        pygame.draw.rect(screen, WHITE, self.rect)

class Menu:
    def __init__(self, mode="player_vs_ai", difficulty=1):
        self.active = True
        self.selected = 0
        self.options = ["Player vs AI", "Player vs Player", "AI vs AI", "Settings", "Quit"]
        self.difficulty_options = ["Easy", "Medium", "Hard"]
        self.selected_difficulty = 1  # Default: Medium
        self.settings_active = False
        self.title_font = pygame.font.Font(None, 74)
        self.option_font = pygame.font.Font(None, 48)
        self.info_font = pygame.font.Font(None, 24)
        
    def handle_input(self, event):
        if event.type == pygame.KEYDOWN:
            if self.settings_active:
                if event.key == pygame.K_ESCAPE:
                    # Exit settings menu
                    self.settings_active = False
                elif event.key == pygame.K_UP:
                    self.selected_difficulty = (self.selected_difficulty - 1) % len(self.difficulty_options)
                elif event.key == pygame.K_DOWN:
                    self.selected_difficulty = (self.selected_difficulty + 1) % len(self.difficulty_options)
                elif event.key == pygame.K_RETURN or event.key == pygame.K_SPACE:
                    # Apply settings
                    self.settings_active = False
            else:
                if event.key == pygame.K_UP:
                    self.selected = (self.selected - 1) % len(self.options)
                elif event.key == pygame.K_DOWN:
                    self.selected = (self.selected + 1) % len(self.options)
                elif event.key == pygame.K_RETURN or event.key == pygame.K_SPACE:
                    if self.selected == 0:  # Player vs AI
                        self.active = False
                        return "player_vs_ai"
                    elif self.selected == 1:  # Player vs Player
                        self.active = False
                        return "player_vs_player"
                    elif self.selected == 2:  # AI vs AI
                        self.active = False
                        return "ai_vs_ai"
                    elif self.selected == 3:  # Settings
                        self.settings_active = True
                    elif self.selected == 4:  # Quit
                        return "quit"
        return None
    
    def draw(self):
        screen.fill(BLACK)
        
        # Draw title
        title = self.title_font.render("PONG", True, WHITE)
        screen.blit(title, (WIDTH // 2 - title.get_width() // 2, 80))
        
        if self.settings_active:
            # Draw settings menu
            settings_title = self.option_font.render("Settings", True, WHITE)
            screen.blit(settings_title, (WIDTH // 2 - settings_title.get_width() // 2, 180))
            
            # Draw difficulty options
            for i, diff in enumerate(self.difficulty_options):
                color = (255, 255, 0) if i == self.selected_difficulty else WHITE
                diff_text = self.option_font.render(diff, True, color)
                screen.blit(diff_text, (WIDTH // 2 - diff_text.get_width() // 2, 250 + i * 50))
            
            # Draw back instruction
            back_text = self.info_font.render("Press ESC to go back", True, WHITE)
            screen.blit(back_text, (WIDTH // 2 - back_text.get_width() // 2, HEIGHT - 50))
        else:
            # Draw menu options
            for i, option in enumerate(self.options):
                color = (255, 255, 0) if i == self.selected else WHITE
                option_text = self.option_font.render(option, True, color)
                screen.blit(option_text, (WIDTH // 2 - option_text.get_width() // 2, 200 + i * 60))
            
            # Draw controls info
            info_text = self.info_font.render("Use UP/DOWN arrows to navigate, ENTER to select", True, WHITE)
            screen.blit(info_text, (WIDTH // 2 - info_text.get_width() // 2, HEIGHT - 50))
        
        pygame.display.flip()

class Game:
    def __init__(self, mode="player_vs_ai", difficulty=1):
        self.difficulty_level = 1  # Starting difficulty level
        # Set game mode
        self.mode = mode
        self.base_difficulty = difficulty
        self.difficulty_level = difficulty
                
        # Create paddles based on mode
        self.player11 = Paddle(20, HEIGHT // 2 - PADDLE_HEIGHT // 2)
        self.player12 = Paddle(WIDTH - 20 - PADDLE_WIDTH, HEIGHT // 2 - PADDLE_HEIGHT // 2)
        
        # In Player vs AI mode, player1 is human, player2 is AI
        # In Player vs Player mode, both are human
        # In AI vs AI mode, both are AI
        self.left_is_ai = self.mode == "ai_vs_ai"
        self.right_is_ai = self.mode == "player_vs_ai" or self.mode == "ai_vs_ai"
        self.ball = Ball()
        self.is_running = True
        self.game_start_time = None
        self.powerups = []
        self.powerup_timer = random.uniform(5, 10)  # First powerup appears after 5-10 seconds
        self.last_powerup_time = time.time()
        
        # Give AI a reference to game for difficulty scaling
        self.player12.game = self
    
    def handle_input(self):
        keys = pygame.key.get_pressed()
        
        # Player 1 controls (Left paddle)
        if not self.left_is_ai:
            if keys[pygame.K_w]:
                self.player11.move(up=True)
            if keys[pygame.K_s]:
                self.player11.move(up=False)
        
        # Player 2 controls (Right paddle) - only in player vs player mode
        if not self.right_is_ai:
            if keys[pygame.K_UP]:
                self.player12.move(up=True)
            if keys[pygame.K_DOWN]:
                self.player12.move(up=False)
        
        # Start the ball if it's not active
        if not self.ball.active and (keys[pygame.K_SPACE] or self.game_start_time and time.time() - self.game_start_time > 1.5):
            self.ball.active = True
    
    def manage_powerups(self):
        current_time = time.time()
        
        # Generate new powerups periodically
        if current_time - self.last_powerup_time > self.powerup_timer and self.ball.active:
            # Only spawn new powerup if there aren't too many
            if len(self.powerups) < 2:
                new_type = random.choice(POWERUP_TYPES)
                self.powerups.append(PowerUp(new_type))
                self.last_powerup_time = current_time
                self.powerup_timer = random.uniform(10, 15)  # Next powerup in 10-15 seconds
        
        # Check for collision with the ball
        for powerup in list(self.powerups):  # Use list copy to avoid modification during iteration
            if powerup.active and powerup.rect.colliderect(self.ball.rect):
                powerup.active = False
                powerup.apply_effect(self.player11, self.player12, self.ball)
                
            # Remove effect after duration expires
            if not powerup.active and powerup.is_applied:
                if current_time - powerup.start_time > POWERUP_DURATION:
                    powerup.remove_effect(self.player11, self.player12, self.ball)
                    self.powerups.remove(powerup)
        
        # Draw active powerups
        for powerup in self.powerups:
            powerup.draw()
            
            # Display remaining time for active effects
            if not powerup.active and powerup.is_applied:
                remaining = POWERUP_DURATION - (current_time - powerup.start_time)
                if remaining > 0:
                    effect_text = pygame.font.Font(None, 20).render(
                        f"{powerup.type.capitalize()}: {remaining:.1f}s", True, powerup.color)
                    screen.blit(effect_text, (10, HEIGHT - 20 * (self.powerups.index(powerup) + 1)))
    
    def update_ais(self):
        # Update left AI if in AI vs AI mode
        if self.left_is_ai:
            self.update_left_ai()
            
        # Update right AI if in player vs AI or AI vs AI mode
        if self.right_is_ai:
            self.update_right_ai()
    
    def update_left_ai(self):
        # Left AI behavior (more aggressive)
        if self.ball.rect.centery < self.player11.rect.centery - 10:
            # Add small chance of AI making a "mistake"
            if random.random() > 0.05:  # More accurate
                self.player11.move(up=True)
        elif self.ball.rect.centery > self.player11.rect.centery + 10:
            if random.random() > 0.05:
                self.player11.move(up=False)
                
    def update_right_ai(self):
        # Simple AI: follow the ball with a slight delay and occasional errors
        if self.ball.rect.centery < self.player12.rect.centery - 10:
            # Add small chance of AI making a "mistake"
            if random.random() > 0.1:  
                self.player12.move(up=True)
        elif self.ball.rect.centery > self.player12.rect.centery + 10:
            if random.random() > 0.1:
                self.player12.move(up=False)
    
    def check_collisions(self):
        # Ball collision with paddles
        if self.ball.rect.colliderect(self.player11.rect) and self.ball.last_hit != self.player11:
            # Calculate where on the paddle the ball hit
            relative_intersect_y = (self.player11.rect.centery - self.ball.rect.centery) / (PADDLE_HEIGHT / 2)
            
            # Reverse horizontal direction
            self.ball.speed_x = abs(self.ball.speed_x) 
            
            # Adjust angle based on where ball hits paddle
            self.ball.speed_y = -relative_intersect_y * 7
            
            self.ball.last_hit = self.player11
            paddle_sound.play()
            
        elif self.ball.rect.colliderect(self.player12.rect) and self.ball.last_hit != self.player12:
            # Calculate where on the paddle the ball hit
            relative_intersect_y = (self.player12.rect.centery - self.ball.rect.centery) / (PADDLE_HEIGHT / 2)
            
            # Reverse horizontal direction
            self.ball.speed_x = -abs(self.ball.speed_x)
            
            # Adjust angle based on where ball hits paddle
            self.ball.speed_y = -relative_intersect_y * 7
            
            self.ball.last_hit = self.player12
            paddle_sound.play()
    
    def update_difficulty(self):
        # Calculate difficulty based on total score
        total_score = self.player11.score + self.player12.score
        self.difficulty_level = 1 + total_score // 3  # Increase difficulty every 3 points
        self.difficulty_level = min(self.difficulty_level, 5)  # Cap at level 5
        
        # Adjust AI speed based on difficulty
        self.player12.speed = 5 + self.difficulty_level
        
        # Display current difficulty level
        difficulty_text = pygame.font.Font(None, 24).render(f"Difficulty: {self.difficulty_level}", True, WHITE)
        screen.blit(difficulty_text, (WIDTH // 2 - 50, 10))
    
    def check_scoring(self):
        # Calculate difficulty based on total score
        total_score = self.player11.score + self.player12.score
        self.difficulty_level = self.base_difficulty + total_score // 3  # Increase difficulty every 3 points
        self.difficulty_level = min(self.difficulty_level, 5)  # Cap at level 5
        # Check if ball goes off screen
        if self.ball.rect.left <= 0:
            self.player12.score += 1
            self.ball.reset(difficulty=self.difficulty_level)
            self.game_start_time = time.time()
            score_sound.play()
        elif self.ball.rect.right >= WIDTH:
            self.player11.score += 1
            self.ball.reset(difficulty=self.difficulty_level)
            self.game_start_time = time.time()
            score_sound.play()
    
    def draw(self):
        # Clear screen
        screen.fill(BLACK)
        self.update_difficulty()
        
        # Draw middle line
        pygame.draw.aaline(screen, WHITE, (WIDTH // 2, 0), (WIDTH // 2, HEIGHT))
        
        # Draw paddles and ball
        self.player11.draw()
        self.player12.draw()
        self.ball.draw()
        
        # Draw scores
        player_score_text = font.render(str(self.player11.score), True, WHITE)
        ai_score_text = font.render(str(self.player12.score), True, WHITE)
        screen.blit(player_score_text, (WIDTH // 4, 20))
        screen.blit(ai_score_text, (3 * WIDTH // 4, 20))
        
        if not self.ball.active and self.game_start_time:
            # Display countdown or "Press SPACE to start" message
            if time.time() - self.game_start_time < 1.5:
                countdown = font.render(str(int(1.5 - (time.time() - self.game_start_time)) + 1), True, WHITE)
                screen.blit(countdown, (WIDTH // 2 - 20, HEIGHT // 2 - 30))
        elif not self.ball.active:
            # Initial game start
            start_text = pygame.font.Font(None, 36).render("Press SPACE to start", True, WHITE)
            screen.blit(start_text, (WIDTH // 2 - 100, HEIGHT // 2 - 18))
        
        # Update display
        pygame.display.flip()
    
    def run(self):
        while self.is_running:
            # Event handling
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.is_running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        self.is_running = False
            
            # Game logic
            self.handle_input()
            self.manage_powerups()
            if self.ball.active:
                self.ball.move()
                self.update_ais()
                self.check_collisions()
                self.check_scoring()
            
            # Drawing
            self.draw()
            
            # Cap the frame rate
            clock.tick(FPS)
        
        pygame.quit()
        sys.exit()

# Main function to handle game flow
def main():
    menu = Menu()
    running = True
    
    while running:
        # Main menu loop
        while menu.active and running:
            # Event handling
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                    menu.active = False
                    continue
                
                # Handle menu input
                result = menu.handle_input(event)
                if result == "quit":
                    running = False
                    menu.active = False
                elif result in ["player_vs_ai", "player_vs_player", "ai_vs_ai"]:
                    # Start game with selected mode
                    difficulty = menu.selected_difficulty + 1  # Convert 0-based index to 1-3 difficulty
                    game = Game(mode=result, difficulty=difficulty)
                    game.run()
                    # Reset menu for when we return
                    menu.active = True
            
            if menu.active:
                menu.draw()
                clock.tick(FPS)
    
    pygame.quit()
    sys.exit()

# Start the game
if __name__ == "__main__":
    main()
