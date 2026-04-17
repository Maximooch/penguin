# Merged April Shipping Timeline — Penguin + Link

_Last updated: 2026-04-01_

This document merges:

- `context/timelines/april_shipping_month.md`
- `context/timelines/link_april_sprint.md`

It does **not** replace either source doc. Those remain the detailed plans for their respective tracks.

---

## Purpose

The two original plans are directionally aligned, but they live separately:

- **Penguin** is the capability engine: hardening, ITUV, MCP, containers, OAK, Link handshake.
- **Link** is the product surface: PM, sessions, approvals, messaging, context, infra.

The practical question is not “what ships first in isolation?”
It is: **what has to land when, so Link becomes daily-drivable while Penguin becomes the infrastructure underneath it?**

---

## Planning Frame

**Combined Window:** Mar 27 – May 14, 2026  
**Core daily-drive target:** May 1, 2026  
**Alpha/Beta hardening target:** May 14, 2026

**Top-level logic:**
1. Harden Penguin enough to be trustworthy.
2. Make Link PM flows coherent.
3. Wire Penguin sessions/approval loops into Link.
4. Add containerized execution and shared context.
5. Finish Link communication surfaces.
6. Harden infra, tests, and deployment.

---

## Executive Timeline

| Window       | Penguin Track                                                       | Link Track                                      | Combined Outcome                                                              |
| ------------ | ------------------------------------------------------------------- | ----------------------------------------------- | ----------------------------------------------------------------------------- |
| Mar 27–31    | Pre-sprint research, architecture, Chrome MCP spike, ITUV design    | Prep / planning context                         | Clear backlog, integration plan, fewer fantasy assumptions                    |
| Apr 1–3      | `0.7.0`–`0.7.1` hardening                                           | Phase 0 — Reality Sync                          | Green builds, canonical docs, baseline stability                              |
| Apr 4–10     | `0.7.2`–`0.7.9` image/video/MCP/skills/MCP server/PR pipeline       | Phase 1 — PM Core Coherence                     | Link PM becomes credible while Penguin gains browser + tooling surface        |
| Apr 10–15    | `0.8.0`–`0.8.4` ITUV, blueprints, TLA+, gateway                     | Phase 2 begins — Penguin Integration + Sessions | Session lifecycle becomes ITUV-aware and more trustworthy                     |
| Apr 15–18    | `0.9.0`–`0.9.3` DX, reports, PM model updates                       | Phase 2 continues                               | Better summaries, orchestration UX, and schema alignment                      |
| Apr 18–22    | `1.0.0`–`1.0.3` containers, SCAR, OAK, episode primitive            | Phase 3 — Containers + Fleet Visibility         | Containerized agent execution and visible fleet operations                    |
| Apr 22–25    | `1.1.0`–`1.1.1` Link handshake + polish                             | Phase 3.5 — Context Management                  | Agents become first-class Link participants with shared context               |
| Apr 26–May 1 | Handshake stabilization, no major new Penguin platform tier planned | Phase 4 — Communication + Social                | Link becomes daily-drivable: messaging, unread, notifications, voice, AI chat |
| May 2–14     | Support hardening, bugfixes, integration cleanup                    | Phase 5 — Infra + Hardening                     | Beta-worthy system with deployment, storage, tests, and production basics     |

---

## Detailed Merged Timeline

## Mar 27–31 — Research, Groundwork, and Design Insurance

### Penguin
- Codebase audit and breakage catalog
- Chrome MCP integration spike
- ITUV design doc
- Sprint backlog + PR pipeline planning

### Link
- No major execution block yet; this period effectively supplies planning input

### Combined objective
- Enter April with an actual dependency map instead of hand-wavy optimism

### Exit signal
- Top 0.7.x issues prioritized
- ITUV draft exists
- Chrome MCP plan exists

---

## Apr 1–3 — Stabilize the Base

### Penguin: `0.7.0`–`0.7.1`
- Hardening pass #1: run-mode stability, PM CRUD reliability, session persistence
- Hardening pass #2: 24/7 mode, automode edge cases, checkpoint reliability

### Link: Phase 0 — Reality Sync
- Fix backend type-check noise
- Freeze canonical docs
- Define beta checklist
- Smoke-test top flows: chat, DM, session, project page, task

### Dependency logic
- Link should not build on Penguin session surfaces while Penguin hardening is still flaky
- This is boring work, which is why it matters

### Exit criteria
- Backend + frontend type-check green
- Canonical roadmap/execution docs chosen
- Known-breakage list written
- Penguin baseline stable enough for integration work

---

## Apr 4–10 — PM Coherence Meets Penguin Capability Expansion

### Penguin: `0.7.2`–`0.7.9`
- `0.7.2` Image tool
- `0.7.3` Video tool
- `0.7.4` Chrome MCP integration
- `0.7.5` Chrome MCP hardening
- `0.7.6` Skills framework v1
- `0.7.7` Skills CLI
- `0.7.8` MCP server
- `0.7.9` PR pipeline live

### Link: Phase 1 — PM Core Coherence
- Apr 4: Project page stabilization
- Apr 5: Task detail polish
- Apr 6: Task views hardening
- Apr 7: Blueprint import
- Apr 8: Cycles + milestones frontend
- Apr 9: Project/task/session linking
- Apr 10: PM integration test pass

### Combined objective
- Make Link’s project/task layer believable **before** layering more session complexity on top
- In parallel, give Penguin the eyes/hands/protocol surface Link will need next

### Key handoff points
- **Apr 9 — Penguin `0.7.8` MCP server:** enables Link exposure of project data as MCP resources
- **Apr 10 — Penguin `0.7.9` PR pipeline:** can begin feeding Link review workflows

### Exit criteria
- Link project page is a real work hub
- Blueprint import is deterministic
- Project ↔ task ↔ session links exist
- Penguin can browse, inspect, and expose capabilities more cleanly

---

## Apr 10–17 — Trust the Session Loop

### Penguin: `0.8.x` then `0.9.x`
- `0.8.0` ITUV core logic
- `0.8.1` ITUV integration
- `0.8.2` Blueprints
- `0.8.3` Basic TLA+
- `0.8.4` Gateway v1
- `0.9.0` Sound notifications
- `0.9.1` Streamlined CLI orchestration
- `0.9.2` Reports / Foreman Dispatch
- `0.9.3` PM data model updates aligned with Link

### Link: Phase 2 — Penguin Integration + Sessions
- Apr 11: Tool approval wired to backend
- Apr 12: Artifact approval wired to backend
- Apr 13: Penguin API surface updated for latest contracts
- Apr 14: Session controls
- Apr 15: Agent work summaries
- Apr 16: Launch points from tasks/projects
- Apr 17: Session integration test pass

### Dependency logic
- This is the first serious trust loop:
  - task launches agent
  - agent executes in session
  - tool/artifact approval round-trips to backend
  - outputs roll back into PM
- If this loop is weak, the rest is decorative nonsense

### Key handoff points
- **Apr 10–12 — Penguin `0.8.0`–`0.8.1`:** Link session UI becomes ITUV-aware
- **Apr 14–15 — Penguin `0.8.4`:** Link can target a persistent Penguin daemon/gateway
- **Apr 17–18 — Penguin `0.9.3`:** schema alignment reduces PM/session mismatch risk

### Exit criteria
- Tool and artifact approval are real backend actions, not local cosplay
- Sessions have trustworthy status/control surfaces
- Agent work summaries are visible and useful
- Users can launch agents directly from PM context

---

## Apr 18–22 — Infrastructure Crossover: Containers, Fleet, OAK

### Penguin: `1.0.x`
- `1.0.0` Container support
- `1.0.1` SCAR runtime
- `1.0.2` OAK multi-agent model
- `1.0.3` Episode primitive

### Link: Phase 3 — Containers + Fleet Visibility
- Apr 18: Docker sandboxing
- Apr 19: Container lifecycle
- Apr 20: Cloud execution groundwork
- Apr 21: Fleet dashboard
- Apr 22: Agent visibility polish

### Dependency logic
- Link’s container story should piggyback on Penguin’s runtime work, not fork it
- Docker-first is the sane move; cloud is stretch, not a hill to die on

### Key handoff points
- **Apr 18–19 — Penguin `1.0.0`:** Link agent sessions can run in Docker
- **Apr 20–21 — Penguin `1.0.2`:** Link fleet dashboard can show execution policies / roles
- **Apr 21–22 — Penguin `1.0.3`:** episode artifacts can support summary/replay/compression patterns

### Exit criteria
- Agent sessions run in Docker containers
- Fleet status is visible in Link
- Agent work is inspectable from task detail
- Session lifecycle includes start/stop/cleanup discipline

---

## Apr 22–25 — Agents Join Link, Context Stops Being an Afterthought

### Penguin: `1.1.x`
- `1.1.0` Link handshake
- `1.1.1` Link polish: presence, status, activity feeds

### Link: Phase 3.5 — Context Management
- Apr 23: Context model design
- Apr 24: Core implementation
- Apr 25: Integration + edge cases

### Dependency logic
- The handshake makes agents first-class Link participants
- Context management makes that useful instead of noisy
- If you skip context design, you get a very fast route to garbage sessions with bloated prompts

### Exit criteria
- Agents can join Link workspaces as real participants
- Sessions receive relevant project/task context on launch
- Context is inspectable and updatable during work

---

## Apr 26–May 1 — Make Link Daily-Drivable

### Penguin
- No new major platform tier scheduled in the source plan after `1.1.1`
- Practical focus should shift to stabilization of handshake/integration behavior

### Link: Phase 4 — Communication + Social
- Apr 26: Messaging baseline blitz
- Apr 27: Notifications + reactions + message search basics
- Apr 28: Voice + calls
- Apr 29: AI chat view
- Apr 30: DM polish + @mentions
- May 1: Communication integration test

### Combined objective
- Ship a credible daily-use workspace:
  - markdown
  - replies
  - unread trust
  - notifications
  - voice/calls
  - AI chat
  - agents present in the workspace

### Important note
- This phase is intentionally after PM/session/context groundwork
- Otherwise you end up polishing chat while the actual work loop is still mush

### Exit criteria
- Messaging no longer feels prototype-grade
- Notifications and unread state are trustworthy enough to use
- AI chat and agents feel native to Link, not bolted on

---

## May 2–14 — Beta Hardening and Deployment

### Penguin
- No explicit new release train in the source doc for this window
- Expected role: bugfixes, integration cleanup, support for Link alpha/beta stabilization

### Link: Phase 5 — Infra + Hardening

#### May 2–5: Core Infra
- Storage backend: S3/R2 uploads
- Deployment pipeline
- Environment hardening
- Database hardening

#### May 6–14: Testing + Polish
- Frontend test coverage
- Playwright smoke suite
- WebSocket hardening
- Error/loading/empty states
- Remove unfinished surfaces
- Beta sweep
- Deploy
- Tag beta release

### Combined objective
- Convert “works in a guided demo” into “survives repeated use without babysitting”

### Exit criteria
- CI/CD is real
- Uploads and auth are real
- Smoke tests catch obvious breakage
- Database and deploy path are credible
- Beta build is externally shareable

---

## Cross-Project Critical Path

These are the real leverage points. Miss them and the rest slides.

1. **Apr 1–3: Hardening + reality sync**
   - If builds/docs are fuzzy here, all downstream planning rots.
2. **Apr 4–10: PM coherence**
   - If project/task flows are weak, agent work has nowhere credible to land.
3. **Apr 10–17: Approval + session trust loop**
   - This is the product core, not an implementation detail.
4. **Apr 18–25: Containers + context + handshake**
   - This is where Penguin stops being a sidecar and becomes infrastructure.
5. **Apr 26–May 14: Communication + beta hardening**
   - This makes the system usable by humans repeatedly, not once.

---

## Weekly Focus View

| Week | Dates | Primary Goal | Failure Mode if Skipped |
|---|---|---|---|
| Week 0 | Mar 27–31 | Research, design, backlog sanity | Building against guesses |
| Week 1 | Apr 1–6 | Stability + PM foundation | New features on broken substrate |
| Week 2 | Apr 7–13 | PM completion + ITUV/session wiring | Fancy agents, weak workflow |
| Week 3 | Apr 14–20 | Session trust + containers | Agents remain sidecar tools |
| Week 4 | Apr 21–27 | Context + handshake + communication baseline | Noise, unclear ownership, brittle collaboration |
| Week 5 | Apr 28–May 4 | Daily-drive communication + infra start | Good demos, bad real usage |
| Week 6 | May 5–11 | Test/hardening sweep | Regression roulette |
| Week 7 | May 12–14 | Deploy + beta tag | Endless “almost ready” syndrome |

---

## Milestone Checkpoints

## Apr 10 — Foundation Checkpoint
- Penguin hardening complete through `0.7.9`
- Link PM hub coherent enough for daily task tracking
- PR pipeline and MCP server available

## Apr 17 — Trust Loop Checkpoint
- ITUV-aware Penguin integration live in Link
- Tool/artifact approvals round-trip to backend
- Sessions launch from PM context and produce usable summaries

## Apr 25 — Core Loop Works
- Docker-based sessions available
- Agents visible in Link
- Context model designed and wired
- Task ↔ session lifecycle feels trustworthy

## May 1 — Daily-Drivable
- Messaging, unread, notifications, voice, AI chat, and agent presence all exist in one coherent workspace story

## May 14 — Alpha/Beta Ready
- Deployable
- Test-backed
- Storage/auth/CI/db basics in place
- No obviously broken surfaces left exposed

---

## Shared Risks

| Risk | Where it bites | Mitigation |
|---|---|---|
| Hardening takes longer than planned | Penguin 0.7.x, Link Phase 0 | Fix top 5 issues only; defer the rest |
| Penguin milestone slip | Link Phases 2–3 | Keep PM and communication work as partial parallel tracks |
| Container/cloud rabbit hole | Penguin 1.0.x, Link Phase 3 | Ship Docker-first; treat ECS/Fargate as stretch |
| Context design vagueness | Link Phase 3.5 | Write the model before coding it |
| Frontend test debt | Link Phase 5 | Add tests during feature work, not only at the end |
| Unread/notification trust failures | Link Phase 4 | Treat unread as deterministic state, not UI glitter |
| PR volume outruns review capacity | Both tracks | Review quality over PR count; reject fast |
| Burnout / over-scheduling | Entire plan | Compress scope before borrowing from health buffer |

---

## What To Cut First If Reality Bites

### Cut first
1. Cloud containers / ECS polish
2. Session replay polish
3. Emoji reactions
4. Message search beyond basics
5. Fancy fleet dashboard visuals

### Do not cut first
1. Tool/artifact approval wiring
2. Project/task/session linking
3. Unread trust
4. Frontend/browser smoke coverage
5. Blueprint import and task generation path

Because yes, the boring plumbing is the product. Shocking, I know.

---

## Bottom Line

This merged plan says one thing clearly:

**Penguin and Link should not be treated as separate April efforts.**
They are one stacked delivery system.

- Penguin ships the runtime, verification, orchestration, and agent capability.
- Link ships the human-facing workflow, review loop, and collaboration surface.

If executed in this order, the likely progression is:

- **Apr 10:** stable base + coherent PM hub
- **Apr 17:** trustworthy session loop
- **Apr 25:** real agent/workspace integration
- **May 1:** daily-drivable internal product
- **May 14:** alpha/beta-worthy release

That is aggressive but coherent. The alternative is shipping disconnected progress theater.
