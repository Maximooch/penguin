# Terminal Aquarium

A calm, deterministic Rich animation for an idle terminal. Fish move at
independent speeds, bubbles rise and respawn, seaweed sways, and water particles
flicker in the background.

## Run

From the repository root:

```bash
python misc/terminal-aquarium/terminal-aquarium.py
```

From this directory:

```bash
cd misc/terminal-aquarium
python terminal-aquarium.py
```

Press `Ctrl-C` to stop an infinite run. The default animation lasts 12 seconds.

## Options

```text
--duration N   Animation length in seconds; 0 runs until Ctrl-C
--fps N        Target frames per second (default: 18)
--seed N       Reproducible fish, plants, bubbles, and particles
--width N      Scene width in characters
--height N     Scene height in rows
--fish N       Number of fish (default: automatic)
--bubbles N    Number of bubbles (default: automatic)
--plants N     Number of seaweed plants (default: automatic)
--fast         Render one static frame and exit
```

Examples:

```bash
python terminal-aquarium.py --duration 0 --seed 42
python terminal-aquarium.py --fast --width 60 --height 16
python terminal-aquarium.py --duration 5 --fps 24 --seed 7
python terminal-aquarium.py --duration 30 --fps 60 --fish 60 --bubbles 300
```

Counts can be set explicitly for stress testing; zero disables that entity.

When stdout is not an interactive terminal, animation is skipped automatically
and one static frame is emitted so the program behaves well in pipes and CI.
