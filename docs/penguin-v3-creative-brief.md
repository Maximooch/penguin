# Penguin Agents — V3 creative brief and section plan

## Direction: The working colony

An asymmetric, editorial company homepage. Link leads the product story. Penguin is introduced alongside it and retains its own identity as an independent open-source coding agent. The penguin characters connect the products through a shared visual language of collaboration and making things.

This is the third company-homepage exploration, not a redesign deployed to Link itself. V1, V2, and the uploaded reference remain unchanged.

## The job of the page

A visitor should understand what the company builds, distinguish the two products, and choose a useful next step. Primary route: explore Link. Secondary route: try the local workflow example. Developer route: explore Penguin's source and quick start.

Link-first is a strategic assumption supplied by Maximus, not a demonstrated conversion result. This prototype lets us evaluate that hierarchy before making it permanent.

## Source basis versus new decisions

The original draft identifies Penguin as an open-source coding agent, Link as an open-source workspace for people and agents, their independent use, support for other agents in Link, and hosting/compute as a future direction—not a current offering. The approved headline is “Build with agents. Work with people.”

The supplied `link-landing-emperor(1).html` and its source archive supply the working-penguin illustrations, the yellow Link glyph, light/dark semantic-surface approach, and the Delegate → Track → Review example. The reference labels its activity as illustrative, which this version also does. The reference's token-provenance comments are not a fresh verification of the repository.

New design decisions in V3: the asymmetric masthead, offset headline, serif emphasis, Link-led workbench, compact Penguin introduction, repositioned native-scale mascots, simplified workflow section, and warmer light-theme palette. These are design judgments, not source-derived facts or claims of measurable uplift.

## Visual system

- Oversized, tightly spaced sans-serif headline. Offset second line. A single serif emphasis provides an editorial counterpoint.
- Warm paper and ink in light mode; near-black navy and warm white in dark mode. Amber marks the primary invitation and preserves the supplied yellow Link identity.
- Asymmetry comes from column widths, offsets, and varied section proportions—not random rotation of readable interfaces.
- Working penguins have jobs: the courier brings the brief, the builder works at the laptop, and the reviewer presents a completed check. They never cover interactive controls or necessary text.
- Use supplied illustration pixels close to native size. No oversized raster mascots or new generated UI screenshots. Existing generated coastal artwork is used once as a quiet visual pause.
- Native system font stacks and Georgia. No font binaries or font-network dependencies.

## Section plan

### 1. Asymmetric opening / Link workbench

Keep the approved company headline. Introduce Link first in the copy and the first substantial product surface. The main HTML workspace demonstrates a docs-search task through Delegate, Track, and Review. A smaller Penguin introduction occupies the adjacent lower column on desktop; on mobile it follows Link in the DOM and visual sequence.

Primary CTA: Explore Link. Secondary CTA: Try the workflow. The current development-site URL is retained as a destination, not represented as a production-launch guarantee.

### 2. Connected workflow

“From ‘can someone…’ to ‘here’s the result.’” Three open, illustrated columns explain the handoff: give the work context, let an agent work through it, then inspect the result and decide. These link back to the same demo, avoiding a second competing walkthrough.

### 3. Penguin, independently

A distinct coding-agent introduction with an HTML terminal illustration. Three sample tasks—build, fix, understand—make the category concrete. Source and quick-start routes are visible. A copyable clone command fetches source only; it is not presented as a complete install command. Copy expressly preserves independent use.

### 4. Company point of view

“More capable. Still in control.” A short statement of design intent, paired with the existing generated Antarctic seascape. Visible decisions and inspectable work take priority over sweeping autonomy claims. No made-up founder quote, customer proof, or performance statistics.

### 5. Practical distinctions

Four concise disclosures cover the relationship between the products, using other agents, the local-only demo, and future infrastructure. Infrastructure is not presented as a third product available today.

### 6. Closing invitation

“Your next idea has company.” Link remains the first action; Penguin is a clear second route. A modest working colony finishes the story. Footer includes both source repositories and a system-theme reset.

## Interaction and engineering

Framework-free HTML, CSS, and JavaScript. One stateful workflow with keyboard tabs, user-controlled progress, inspectable sample evidence, an example approval decision, change-request validation, and reset. The page sends no feedback, runs no agents, and changes no repository. No backend, tracking, analytics, cookies, or external JavaScript.

Theme follows the device initially. Explicit light/dark choice persists when storage is available. A footer control restores device preference. Theme setup happens before first paint; storage denial does not prevent use. Both themes use semantic surface and state variables.

Mobile is a reflow, not a shrunken desktop screenshot. Hide nonessential sidebar detail; retain readable content and meaningful actions. Decorative motion is short and does not move controls under the cursor. Respect reduced motion. No scroll hijacking, autoplay hero, or endlessly moving elements.

## Acceptance and publication

Test both themes across phone, tablet, and desktop widths; keyboard tab navigation; dialog close/return focus; approval and feedback; theme persistence/system changes/storage denial; mobile navigation; local single-file use; reduced motion; and no-JavaScript content. Inspect screenshots, not just DOM measurements. Record actual results separately from this intended test plan.

Before publication, confirm current product readiness, link destinations, production-domain metadata, and applicable policy/footer requirements. Replace the prototype's `noindex` and set absolute canonical/social metadata only after selecting the production domain.

## What remains unproven

This is a design implementation, not evidence of better conversion or complete accessibility compliance. A useful next real-world check is an unprompted five-second comprehension test: what does the company sell, how do Link and Penguin differ, and where would you click? Cross-browser and assistive-technology checks remain separate from the local automated tests.
