# Cross-Platform Interactive VM Test Environments

## Goal

Establish disposable, reproducible interactive desktop environments for Penguin usage testing on:

- Windows 11
- a mainstream Linux desktop
- macOS on licensed Apple hardware

Layer 1 CI coverage already exists. This task concerns Layer 2: real GUI/terminal environments where Penguin can be installed and exercised like an end user would use it.

## Why This Layer Exists

Hosted CI runners answer whether Penguin installs and passes scripted checks on each operating system. They do not fully reproduce:

- a standard Windows 11 user profile and Windows Terminal
- interactive keyboard handling, focus, clipboard, DPI, and terminal rendering
- first-run prompts under a normal non-development account
- RDP/VNC behavior and desktop security defaults
- macOS terminal, permissions, keychain, and Apple Silicon behavior
- long-running cancellation or cleanup behavior visible to a human tester

The purpose is not to maintain a permanent multi-OS fleet. The preferred model is disposable infrastructure created for a test session, instrumented, and destroyed afterward.

## Recommended Service Mix

### Windows 11: Azure DevTest Labs or Azure VM

Preferred starting point because Windows 11 Pro images, reusable images/formulas, RDP, expiration, and auto-shutdown fit interactive product testing well.

Target base image:

- Windows 11 Pro
- ordinary non-admin test user where practical
- Windows Terminal
- PowerShell
- Git
- `uv`
- browser for GitHub authentication and artifact retrieval
- screenshot and screen-recording support

Do not bake Penguin into the reusable image. Installing Penguin during each test is part of the product flow being tested.

### Linux Desktop: Azure, AWS, or another commodity VM

Use Ubuntu Desktop or an Ubuntu VM with a deliberately configured desktop and remote-display stack. A server-only shell is insufficient for validating terminal rendering and desktop behavior.

Target base image:

- supported Ubuntu LTS desktop
- GNOME Terminal and/or another common terminal
- SSH plus RDP/VNC fallback
- Git and `uv`
- non-root test user

Linux GUI testing can initially be lower frequency than Windows because Layer 1 already provides broad Linux coverage. Promote it when desktop-specific regressions appear.

### macOS: Scaleway Apple Silicon, AWS EC2 Mac, or MacStadium

macOS cloud execution requires Apple hardware and is therefore more expensive and operationally constrained.

Recommended progression:

1. Scaleway Apple Silicon for occasional manual sessions.
2. AWS EC2 Mac if consolidating infrastructure in AWS is valuable.
3. MacStadium/Orka if recurring ephemeral macOS environments become a real operational need.

Account for provider minimum lease/allocation periods. Batch macOS tests into planned sessions rather than launching hardware for one five-minute check.

## Alternative: Single-Provider AWS

AWS can supply Linux, Windows Server, and native macOS hardware under one account. It is operationally convenient but has two important limitations:

- standard EC2 Windows images are generally Windows Server, not representative Windows 11 consumer desktops;
- EC2 Mac is dedicated bare-metal capacity with higher cost and minimum allocation constraints.

AWS is a reasonable consolidation option, but Azure Windows 11 plus a separate macOS service provides better test fidelity for Penguin's immediate needs.

## Environment Lifecycle

Each test environment should support this lifecycle:

1. Provision from a versioned base image or infrastructure template.
2. Create a fresh non-development user profile.
3. Pull the target branch or package artifact.
4. Install Penguin as a user would.
5. Run the GUI/user test checklist.
6. Collect logs, screenshots, recordings, config, timings, and environment metadata.
7. Upload artifacts to a durable location associated with the commit or test run.
8. Destroy the instance automatically.

Avoid mutable long-lived machines. They accumulate credentials, package caches, configuration, stale workspaces, and exactly the sort of accidental state that first-run testing is supposed to expose.

## Provisioning Requirements

- Infrastructure represented in code where the provider supports it.
- Automatic shutdown and hard expiration enabled by default.
- Unique machine and test-run identifiers.
- No production credentials.
- Dedicated low-privilege test provider credentials when live model access is required.
- Secret injection at test time; secrets must not be included in images or recordings.
- Ability to create both a clean profile and a deliberately preconfigured profile.
- Branch or artifact selection without rebuilding the base image.
- Logs and test artifacts exported before destruction.

## Suggested Environment Matrix

| Environment | Primary purpose | Frequency |
|---|---|---|
| Windows 11 + Windows Terminal | Fresh install, onboarding, input/cancel, paths, permissions | Every release candidate and relevant PR |
| Ubuntu LTS Desktop | Terminal rendering and desktop integration | Release candidate or desktop-related PR |
| Current supported macOS on Apple Silicon | Installation, Terminal behavior, permissions, architecture | Batched release testing |
| Optional Windows Server | Package/runtime compatibility only | Automated or occasional |

Test at normal display scaling first. Add one Windows high-DPI profile after the core workflow is stable.

## Cost Controls

- Default to the smallest VM that provides responsive interactive testing.
- Require auto-shutdown and expiration during provisioning.
- Tag resources with repository, branch, commit, owner, and expiration.
- Provide a cleanup command that removes all resources for a test run.
- Use snapshots/images for prerequisites, not for Penguin state.
- Batch macOS checks within the provider's minimum billing window.
- Add a monthly budget alert before adding automation that can create machines.

## Security Controls

- Use isolated test accounts/subscriptions/projects where possible.
- Do not use personal provider keys inside reusable images.
- Rotate dedicated test credentials regularly.
- Redact environment variables and `.env` contents from collected diagnostics.
- Disable public inbound access except the minimum remote desktop/SSH path.
- Prefer VPN, provider session manager, or IP allowlisting over open RDP/VNC.
- Destroy machines after artifact collection.

## Proof-of-Concept Plan

### Phase 1: Windows 11

- [ ] Select Azure DevTest Labs versus a direct Azure VM template.
- [ ] Create a Windows 11 base image with Git, `uv`, and Windows Terminal.
- [ ] Add auto-shutdown and a maximum lifetime.
- [ ] Document RDP connection and teardown.
- [ ] Run a clean Penguin install and workspace-only onboarding.
- [ ] Record abort-to-idle latency for a running prompt.
- [ ] Export logs, screenshots, and environment metadata.
- [ ] Recreate from scratch and confirm the result is reproducible.

### Phase 2: Linux Desktop

- [ ] Provision Ubuntu LTS Desktop with a non-root user.
- [ ] Validate terminal rendering, setup, workspace paths, and cancellation.
- [ ] Confirm remote desktop does not alter the tested keybindings.
- [ ] Export the same artifact shape as Windows.

### Phase 3: macOS

- [ ] Compare one-session cost and provisioning friction for Scaleway, AWS, and MacStadium.
- [ ] Provision Apple Silicon macOS hardware.
- [ ] Validate fresh installation, shell environment, Terminal behavior, permissions, and cancellation.
- [ ] Decide whether occasional manual sessions are sufficient or Orka-style orchestration is justified.

## Selection Criteria

Score candidate services on:

- fidelity to a real end-user OS
- startup/provisioning time
- API and infrastructure-as-code support
- interactive remote desktop quality
- snapshot/image support
- automatic expiration and cleanup
- artifact extraction
- pricing granularity and minimum allocation
- regional availability
- security controls
- ability to use ordinary, non-admin user accounts

## Exit Criteria

- [ ] A documented provider choice exists for each required OS.
- [ ] Windows 11 can be provisioned and destroyed repeatably.
- [ ] At least one clean-profile Penguin test has been recorded on Windows 11.
- [ ] Linux desktop and macOS options have measured cost and setup time.
- [ ] Every environment has automatic shutdown/expiration.
- [ ] Test artifacts can be associated with a branch and commit.
- [ ] No reusable image contains Penguin config, workspace data, or provider secrets.

## Relationship To Other Tasks

- `context/tasks/gui-testing.md` defines what to automate and what evidence to collect inside these environments.
- `context/tasks/tui-testing.md` remains the functional TUI validation checklist.
- `context/tasks/testing-pyramid.md` describes where interactive system testing fits relative to deterministic automated tests.
