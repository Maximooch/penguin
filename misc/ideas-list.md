# Terminal Gadget Ideas

Small, useful terminal widgets with enough visual polish to make routine work more engaging. Prefer shared Rich primitives (`Live`, fixed-width panels, status badges, timers, and non-TTY fallbacks) over one-off rendering hacks.

## High-Value Gadgets

### Repo Vital Signs
A compact dashboard for the current repository:

- Git branch and dirty-file count
- Recent commit and working-tree age
- Test/lint status
- TODO/FIXME count
- Largest or most-changed files

### Focus Reactor
A Pomodoro-style focus timer with escalating visual phases:

- Focus, short break, and long break modes
- Progress ring or reactor-core animation
- Session history and completed cycles
- Optional task label and timebox

### Test Gauntlet
A visual test runner that presents checks as lanes or gates:

- Lint, unit tests, integration tests, build, and smoke checks
- Live pass/fail/running states
- Failed-command summaries
- A final “all gates clear” or “blocked” state

### Log Telescope
A live log viewer designed for signal over noise:

- Severity filtering and search
- Highlighted errors and warnings
- Event-rate sparkline
- Pause/follow mode
- File or stdin input

### Bug Triage Deck
A card-based TODO and issue picker:

- Import TODO/FIXME comments or a simple issue file
- Show impact, effort, confidence, and age
- Pick the next smallest high-leverage task
- Mark items as accepted, deferred, or rejected

### Commit Message Slot Machine
A constrained commit-message generator:

- Choose type, scope, and change summary
- Follow the repository’s commit convention
- Show several candidates and let the user select one
- Avoid pretending randomness can replace understanding the diff

### Dependency Weather
A playful dependency health report:

- Fresh, aging, stale, vulnerable, or unknown categories
- Weather-style icons and summary forecast
- Separate direct and transitive dependencies
- Links or commands for follow-up

### Build Conveyor Belt
An animated pipeline for development checks:

- Lint → test → package → deploy stages
- Each stage has queued, running, passed, and failed states
- Show the active command and elapsed time
- Preserve the final report after the animation

### Terminal Aquarium
A calm ambient aquarium for an otherwise idle terminal:

- Fish swim at independent speeds and directions
- Bubbles rise and reset
- Seaweed and water particles add depth
- Motion remains deterministic with a seed
- It must fall back to a clean static frame when output is not a TTY

### Entropy Meter
A repository-disorder score with explainable inputs:

- TODO/FIXME count
- Failing tests and lint errors
- Oversized files
- Stale branches or uncommitted work
- Missing documentation and setup friction

The score should be a diagnostic aid, not fake precision.

## Shared Building Blocks

Build these once and reuse them across the gadgets:

- `LiveDashboard` for in-place terminal redraws
- `StatusBadge` for consistent state colors
- `ProgressPhase` for explicit lifecycle states
- `KeyHint` for interactive controls
- `FixedCanvas` for deterministic-width ASCII scenes
- `NonTTYRenderer` for pipes, CI logs, and redirected output
- Deterministic random seeds for demos and tests

## Suggested Order

1. Terminal Aquarium — establish ambient animation and canvas primitives.
2. Focus Reactor — add timers and phase transitions.
3. Repo Vital Signs — connect a dashboard to real repository data.
4. Build Conveyor Belt — add subprocess lifecycle and command output.
5. Test Gauntlet — reuse the pipeline state model with test-specific UX.
6. Log Telescope — add streaming input and filtering.
7. Bug Triage Deck — add structured task selection.
8. Dependency Weather — add package metadata and vulnerability data.
9. Entropy Meter — combine repository signals into an explainable report.
10. Commit Message Slot Machine — add diff-aware generation last.
