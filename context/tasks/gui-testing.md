# GUI And Synthetic User Testing Plan

## Goal

Build a small, reliable layer of semi-automated user testing for Penguin's real terminal UI and first-run experience across Windows, Linux, and macOS.

This is not a replacement for unit, API, PTY, or integration tests. GUI automation should cover the narrow set of failures that only appear when a real user launches a real terminal in a real desktop session.

## Testing Principle

Prefer the lowest layer that can prove the behavior:

1. unit/service test
2. API/integration test
3. PTY or terminal-process test
4. native accessibility/UI automation
5. image/coordinate automation
6. manual exploratory testing

Pixel-based automation is the last programmable resort, not the default. Coordinates, fonts, terminal dimensions, animations, remote desktop scaling, and OS updates make purely visual scripts brittle.

## Scope

Initial GUI coverage should focus on Penguin's highest-risk user journeys:

- fresh installation
- first launch and workspace onboarding
- skipping AI model/provider/credential setup
- launching the TUI without OpenRouter or another provider key
- connecting a provider later
- submitting a prompt
- interrupting streaming or tool execution with `Esc`
- exiting cleanly
- rerunning setup without losing existing configuration
- Windows path, terminal, focus, and keyboard behavior

Do not attempt to automate every TUI command. Stable GUI coverage of ten critical journeys is more valuable than a large suite that fails whenever a spinner moves.

## Test Layers

### Layer A: PTY And Process-Level Tests

Use a pseudo-terminal or terminal process harness to automate deterministic input/output behavior without a desktop.

Assert:

- prompts appear in the expected order;
- Enter accepts the default workspace;
- Skip choices produce a workspace-only config;
- startup does not require `OPENROUTER_API_KEY`;
- prompt submission without a provider returns actionable guidance;
- `Esc` or the corresponding interrupt control reaches the abort path;
- the process exits with the expected code;
- no child process is leaked.

PTY tests should provide most of the automated coverage because they are fast and can run in CI.

### Layer B: Native Accessibility Automation

Use OS accessibility/UI frameworks for opening terminals, typing commands, locating windows, and reading controls when exposed.

Candidate tools:

- Windows: FlaUI, pywinauto, PowerShell UI Automation, or WinAppDriver-compatible tooling.
- macOS: XCTest UI automation, Accessibility APIs, or AppleScript for narrow orchestration.
- Linux: AT-SPI tooling such as Dogtail.

For terminal content, prefer reading application logs, process state, or structured test signals instead of OCR when possible.

### Layer C: Image And Coordinate Automation

Use PyAutoGUI, SikuliX, or equivalent only for interactions that are not available through accessibility APIs.

Requirements:

- fixed viewport and terminal dimensions;
- controlled display scaling;
- explicit wait conditions rather than arbitrary sleeps;
- screenshots before and after important actions;
- retry only for known environmental timing, never to hide a product race;
- visual baselines scoped by OS and terminal application.

### Layer D: Manual Exploratory Sessions

Reserve manual testing for:

- visual quality and comprehensibility;
- unfamiliar failures;
- OS updates and new terminal versions;
- provider/network behavior;
- accessibility and keyboard ergonomics;
- exploratory attempts to break onboarding or cancellation.

Manual findings should become lower-level automated regressions whenever the failure can be expressed deterministically.

## Harness Architecture

Use a controller plus an in-VM test runner.

### Controller

Responsible for:

- selecting OS, image, branch, commit, and scenario;
- provisioning or connecting to the environment;
- injecting non-production test credentials when required;
- starting recording;
- invoking the scenario runner;
- collecting results;
- shutting down and destroying the VM.

### In-VM Runner

Responsible for:

- creating a fresh OS user/config state;
- installing Penguin from the selected branch or artifact;
- launching the terminal application;
- performing inputs through the selected UI driver;
- observing structured process/API/log signals;
- taking screenshots at checkpoints;
- writing a machine-readable result file;
- redacting secrets before artifact upload.

Keep scenario definitions independent of provider infrastructure so the same user journey can run on Windows, Linux, and macOS with platform-specific drivers.

## Stable Test Hooks

Add testability hooks only when they improve observability without changing normal behavior.

Useful hooks may include:

- deterministic session/run identifiers;
- structured session status events with timestamps;
- startup phase logging;
- an environment variable selecting a temporary config/workspace root;
- a test-only fake provider with controllable streaming and cancellation;
- a command or endpoint that reports current run state;
- explicit process exit and child-process diagnostics;
- optional suppression of nonessential animations for visual baselines.

Avoid adding a hidden GUI-only code path that users never exercise. The test should drive the real launch and cancellation flows.

## Fake Provider For Deterministic Testing

A local fake provider should support:

- immediate response;
- controlled token streaming rate;
- stream that hangs until cancelled;
- tool request followed by delayed cleanup;
- provider error;
- disconnect during streaming;
- configurable cancellation acknowledgement delay.

This makes abort latency and state transitions deterministic without spending provider credits or depending on the public internet.

Use live providers only for a separate smoke scenario.

## Initial Synthetic User Journeys

### G1: Fresh Install, Skip Model

1. Start with no Penguin config, workspace, or provider environment variables.
2. Install Penguin using the documented command.
3. Launch `penguin`.
4. Accept or enter a workspace path.
5. Choose **Skip for now** for connecting an AI model.
6. Confirm the TUI launches.
7. Confirm no OpenRouter credential error is shown.
8. Exit cleanly.

Evidence:

- terminal recording;
- generated config with secrets redacted;
- startup logs;
- screenshot of launched TUI;
- exit code.

### G2: Prompt Without Connected Model

1. Complete workspace-only onboarding.
2. Submit a prompt.
3. Confirm Penguin displays actionable **Connect an AI model** guidance.
4. Confirm the TUI remains usable and does not crash.

### G3: Configure Provider Later

1. Begin from workspace-only configuration.
2. Run `penguin config setup` or use the TUI connection surface.
3. Select a provider and model.
4. Supply a dedicated test credential or choose a local fake provider.
5. Launch or return to the TUI.
6. Send a simple prompt and confirm a response.

### G4: Cancel Streaming

1. Start a deterministic slow stream.
2. Wait for running/streaming state.
3. Press `Esc` once.
4. Measure:
   - keypress to abort request;
   - abort request to idle event;
   - keypress to TUI idle rendering;
5. Confirm no repeated `Esc` is required.
6. Confirm partial output is stable and the next prompt can be submitted.

Initial target: the session should return to idle in under one second in the deterministic local scenario. Track real-provider latency separately.

### G5: Cancel During Tool Cleanup

1. Start a fake-provider flow that invokes a deliberately slow tool cleanup.
2. Press `Esc` once.
3. Confirm the request task is cancelled and the TUI becomes idle before tool cleanup completes.
4. Confirm cleanup finishes or times out without reviving the session.
5. Confirm no orphan process remains.

### G6: Rerun Setup

1. Begin with an existing workspace and connected model.
2. Run setup again.
3. Accept the existing workspace default.
4. Skip the optional connection step.
5. Confirm the existing model remains configured.
6. Repeat from workspace-only configuration and confirm it remains provider-free.

### G7: Windows Paths And Permissions

1. Use a workspace path with spaces and non-ASCII characters.
2. Test the default user home path and a user-selected path.
3. Confirm directory creation and config serialization.
4. Confirm launching from a different current directory does not change the selected workspace unexpectedly.
5. Confirm clear errors for unwritable locations.

### G8: Exit Behavior

Validate idle and busy behavior from `context/tasks/tui-testing.md`:

- `Ctrl+D` exits while idle;
- configured quit key exits while idle;
- `Ctrl+C` clears input as designed;
- `Esc` interrupts while busy;
- busy exit confirmation behaves correctly;
- no server or tool child process remains.

### G9: Offline First Run

1. Disable external network access.
2. Start with no config.
3. Complete workspace onboarding and skip model setup.
4. Confirm no remote model catalog is requested.
5. Confirm the TUI launches.

### G10: Install/Upgrade Boundary

1. Install the previous release and create a representative config.
2. Upgrade to the candidate branch/package.
3. Launch Penguin.
4. Confirm existing users are not forced through destructive onboarding.
5. Confirm workspace and model settings remain intact.

## Assertions And Evidence

Prefer structured assertions:

- process running/exited;
- HTTP response status;
- session state;
- emitted event timestamp;
- generated config shape;
- child process count;
- log markers;
- filesystem state.

Use visual assertions for:

- required prompt or notice is visible;
- TUI is not blank or visibly corrupted;
- focus is in the expected input;
- running/idle indicator changes;
- dialogs render inside the viewport.

Every failed GUI scenario should retain:

- OS image/version;
- terminal application/version;
- display resolution and scaling;
- Penguin branch and commit;
- install command and package version;
- scenario inputs;
- structured result JSON;
- relevant logs;
- screenshots;
- short recording when available.

## Result Schema

Write one result document per scenario:

```json
{
  "scenario": "G4-cancel-streaming",
  "os": "windows-11",
  "os_version": "...",
  "terminal": "Windows Terminal",
  "penguin_commit": "...",
  "install_seconds": 18.4,
  "onboarding_completed": true,
  "provider_skipped": false,
  "tui_launched": true,
  "abort_request_ms": 85,
  "idle_event_ms": 210,
  "idle_render_ms": 265,
  "process_leaked": false,
  "status": "passed",
  "artifacts": [
    "session.log",
    "screen.mp4",
    "after-abort.png"
  ]
}
```

Do not place credentials, complete environment dumps, or unredacted `.env` files in results.

## Flake Policy

A GUI test may be retried once only when infrastructure failure is clearly identified, such as an RDP disconnect or VM provisioning error.

Do not automatically retry:

- a missing prompt;
- a stuck busy state;
- cancellation latency above threshold;
- a crash;
- incorrect configuration;
- leaked processes.

Record timing distributions rather than adding longer sleeps. A 30-second sleep can make a race disappear while preserving the bug; it is a sedative, not a test strategy.

## Implementation Phases

### Phase 1: Manual Protocol With Structured Evidence

- [ ] Finalize G1-G10 steps.
- [ ] Create a result JSON template.
- [ ] Add scripts to collect versions, logs, process state, and config shape.
- [ ] Run the protocol manually on one Windows 11 VM.
- [ ] Record ambiguity and remove steps that depend on subjective interpretation.

### Phase 2: Deterministic Terminal Harness

- [ ] Add a local fake streaming provider.
- [ ] Automate install, launch, onboarding responses, and exit at PTY/process level.
- [ ] Add timestamped cancellation assertions.
- [ ] Run the deterministic subset on all Layer 1 operating systems.

### Phase 3: Windows GUI Driver

- [ ] Select pywinauto/FlaUI versus another Windows-native driver.
- [ ] Automate opening Windows Terminal and launching Penguin.
- [ ] Automate G1, G4, G5, and G8.
- [ ] Collect screenshots and recording automatically.
- [ ] Validate with normal and high-DPI display profiles.

### Phase 4: Linux And macOS Drivers

- [ ] Reuse scenario definitions and structured assertions.
- [ ] Implement only platform-specific launch/input/observation adapters.
- [ ] Avoid copying scenario logic into three unrelated suites.
- [ ] Measure maintenance cost before expanding beyond critical journeys.

### Phase 5: Scheduled And Release Testing

- [ ] Run deterministic PTY scenarios on relevant PRs.
- [ ] Run interactive Windows scenarios on release candidates and onboarding/TUI changes.
- [ ] Run Linux desktop and macOS scenarios on a schedule or release gate.
- [ ] Publish a compact cross-platform result report with artifact links.

## Exit Criteria

- [ ] Critical journeys G1-G10 have unambiguous expected outcomes.
- [ ] A local fake provider makes streaming and cancellation deterministic.
- [ ] At least G1, G4, G5, and G8 run semi-automatically on Windows 11.
- [ ] Abort-to-idle latency is measured rather than judged manually.
- [ ] Failures retain enough evidence to reproduce without the original VM.
- [ ] GUI failures are converted to lower-level regression tests when possible.
- [ ] The suite does not depend on personal credentials or persistent user state.

## Relationship To Other Tasks

- `context/tasks/cross-platform-interactive-vms.md` covers infrastructure and environment lifecycle.
- `context/tasks/tui-testing.md` defines existing TUI functional checks.
- `context/tasks/testing-pyramid.md` defines the broader assurance hierarchy.
- `context/tasks/testing_scenarios.md` contains additional product testing scenarios that can be promoted into synthetic user journeys.
