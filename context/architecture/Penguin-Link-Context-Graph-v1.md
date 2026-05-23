# Penguin-Link Context Graph v1

**Purpose:** Unified specification for the Context Graph used by Penguin agents locally and by Link workspaces in the cloud.
**Audience:** Maximus, future contributors, agents reading their own spec.
**Status:** Draft 1. The Context Graph section is concrete enough to implement. The Coherence Layer section is partly speculative and has open research questions.
**Date:** 2026-05-13
**Author:** Maximus Putnam

---

## TL;DR

The Penguin-Link Context Graph is **a bitemporal, provenance-typed graph that is workspace-owned from line one**, designed to be queryable by both fast deterministic code and slow LLM reasoning, with **a separate Coherence Layer that maintains agent-level attention and compression dynamics** over the workspace's evolving state.

Two distinct architectural layers:

| Layer | What it is | Lifetime | Granularity | Analogy |
|---|---|---|---|---|
| **Context Graph** | Durable, bi-temporal, queryable knowledge structure | Months to years | Facts, entities, edges | Long-term + episodic memory |
| **Coherence Layer** | Attention-modulated, per-agent workspace understanding | Minutes to weeks | Compressed/decompressed episodes + schemata | Working memory + autobiographical recall |

Both layers are **workspace-scoped from the beginning**. Cross-workspace sharing uses explicit bridges, not retrofitted ACLs. The same model serves Penguin running on a laptop (single workspace, NetworkX backend) and Link in the cloud (multi-tenant, Graphiti on Neo4j). The application code is identical; the deployment differs.

The novel contribution against the field is **Glass-typed provenance on every node and edge** plus **the Coherence Layer as a first-class architectural component** (not just a memory tool the agent calls into). No incumbent has either.

---

## 1. Design principles

These are non-negotiable. Everything in the spec follows from them.

1. **Workspace-owned from line one.** Every node, every edge, every operation carries `workspace_id`. There is no "global" graph except as the union of bridged workspaces. Multi-tenancy is structural, not a feature.
2. **Bi-temporal by default.** Every fact tracks both event-time and ingestion-time. Inherited from Graphiti/Zep.
3. **Provenance is structural, not metadata.** Every node and edge carries Glass-style lineage. This is the novel contribution.
4. **Two retrieval modes.** Fast deterministic for hot paths; slow LLM reasoning for meta-loops.
5. **Cost-typed operations.** Every reasoning call has a `@cost` annotation; budget enforced per session via C\$ discipline.
6. **Non-lossy episodic storage.** Raw events preserved with bidirectional links to derived semantic artifacts.
7. **Cross-workspace via bridges, never via flat access.** No "user X can read workspace Y" — only "workspace Y has granted workspace X a bridge with scoped capabilities."
8. **Coherence is per-agent.** Different agents in the same workspace have different attention states. Schemata extracted by one agent can be promoted to the Graph for others to inherit.
9. **Local-first, scale-later.** NetworkX in-process for v1; Graphiti on Neo4j when needed. Same API.

---

## 2. Workspace ownership (the multi-tenant primitive)

This section comes before the graph types because the workspace structure constrains everything else.

### The data model

```
Workspace
├── id: WorkspaceId
├── owned_subgraph: Subgraph         # everything created here
├── bridges_in: list[BridgeGrant]    # what other workspaces have shared with us
├── bridges_out: list[BridgeGrant]   # what we have shared with others
├── coherence_layers: dict[AgentId, CoherenceState]  # per-agent attention
├── members: list[PrincipalId]       # humans + agents
└── policies: WorkspacePolicy        # default capability grants, audit rules
```

Every node and edge has a `workspace_id`. The fast path for any query is "first filter by visible workspaces, then apply the query." This is identical to the way Link's existing data layer works (workspace as the trust boundary), so the Context Graph inherits Link's existing multi-tenancy primitives directly.

### Bridges (cross-workspace primitive)

A bridge is a typed, scoped capability grant from one workspace to another. Modeled on Link's existing `channelWorkspaceLink` / `agentWorkspaceLink`:

```cash
BridgeGrant {
    from: WorkspaceId
    to: WorkspaceId
    scope: SubgraphSelector              # which subgraph is exposed
    capabilities: list[Capability]       # read, query, observe-changes, write?
    valid_from: DateTime
    valid_until: DateTime | "indefinite"
    audit_to: ChannelRef | None          # where bridge usage is logged
    pricing: PaymentTerms | None         # C$-typed, if applicable
}
```

Examples of what this enables:

- A supply-chain workspace can grant a procurement workspace read-access to its supplier capability subgraph for $0.05 per query.
- A research workspace can grant a trading workspace observe-access to its company-events subgraph, with the trading workspace paying a flat monthly retainer.
- A team workspace can bridge a partner agency's design subgraph for collaboration, free, time-bounded.

Bridges are the only legitimate cross-workspace operation. There is no flat "make this graph public." Public means "bridged to a designated `public` workspace anyone can read from."

### Why this matters from day one

Building single-tenant then multi-tenant is a category of refactoring that often kills projects. The cost of designing for multi-tenancy on day one is small (an extra column on every row); the cost of retrofitting is sometimes prohibitive (every query rewritten, every cache invalidated, every test suite revisited). Penguin-Link Context Graph is multi-tenant from line one because Link is multi-tenant from line one, and the autopoietic / Link Express / Data Market visions all require cross-workspace operation as a first-class primitive.

---

## 3. Layer 1: The Context Graph

### Core types

```python
# === Identity & ownership ===

WorkspaceId   = NewType("WorkspaceId", UUID)
NodeId        = NewType("NodeId", UUID)        # UUIDv7 for sortability
EdgeId        = NewType("EdgeId", UUID)
EpisodeId     = NewType("EpisodeId", UUID)
AgentId       = NewType("AgentId", UUID)

# === Node types ===

class Node:
    id: NodeId
    workspace_id: WorkspaceId          # required, structural
    type: NodeType                     # "peer" | "concept" | "event" | "market" | ...
    name: str
    properties: dict
    provenance: Provenance             # Glass layer
    
class Peer(Node):                      # any entity (human, agent, group, idea)
    type = "peer"
    representations: PeerCard          # Honcho-style aggregated representation
    observation_scope: list[NodeId]
    
class Market(Node):                    # example domain-specific
    type = "market"
    venue: str
    contract_id: str
    last_quote: Quote                  # reactive, derived

class Concept(Node):
    type = "concept"
    embedding: Vector                  # semantic retrieval

class Artifact(Node):                  # file, document, message, code
    type = "artifact"
    content_ref: ContentRef            # content-addressed pointer
    
class Event(Node):                    # something that happened
    type = "event"
    occurred_at: DateTime

# === Edge types ===

class Edge:
    id: EdgeId
    workspace_id: WorkspaceId          # required
    source: NodeId
    target: NodeId
    type: RelationType                 # "knows" | "owns" | "implies" | "contradicts" | ...
    epistemic_status: Status           # see below
    confidence: float                  # [0, 1]
    
    # Bi-temporal (Graphiti)
    t_valid: DateTime
    t_invalid: DateTime | None         # superseded? when?
    t_created: DateTime
    t_expired: DateTime | None         # marked stale? when?
    
    # Provenance (Glass)
    provenance: Provenance

class EpistemicStatus(Enum):
    OBSERVED   = "observed"            # direct sensor reading
    INFERRED   = "inferred"            # derived from other edges
    ASSERTED   = "asserted"            # claimed by a peer, not yet verified
    CONTESTED  = "contested"           # disagreement between sources
    SUPERSEDED = "superseded"          # an old version of a later edge
    HYPOTHETICAL = "hypothetical"      # speculative, not committed

# === Provenance (the Glass layer) ===

class Provenance:
    source_episode: EpisodeId          # raw event this came from
    derived_by: AgentId                # which Penguin agent extracted it
    model: ModelRef                    # which LLM made the call
    prompt_hash: bytes
    cost: Money                        # how much this fact cost to derive (C$)
    verified_by: list[VerificationRecord]  # cross-model checks
    
    # Optional Glass extensions (v2+)
    features: list[Feature] | None     # SAE features active at derivation
    attention: AttentionTrace | None
    counterfactual_robustness: float | None
```

### Subgraph organization

Five layers, all workspace-scoped:

1. **Episodic subgraph** — raw events, messages, observations. Append-only.
2. **Semantic subgraph** — extracted entities and relationships. Editable via temporal invalidation.
3. **Provenance subgraph** *(Penguin contribution)* — lineage of derivations. Every semantic node links back to its episodic source AND its derivation event. This subgraph is what makes traces sellable on the Data Market.
4. **Peer subgraph** *(Honcho contribution)* — aggregated representations of peer entities; refreshed by the deriver.
5. **Coherence ledger** *(novel)* — per-agent attention history; what was salient when. Feeds the Coherence Layer (Section 4).

### Retrieval APIs

Two modes, two APIs:

**Fast retrieval (deterministic, milliseconds, no LLM)**:

```python
graph.get_node(id) -> Node
graph.neighbors(node_id, edge_types=[...]) -> list[Node]
graph.shortest_path(source, target) -> list[Edge]
graph.facts_about(entity_id, at_time=t) -> list[Edge]  # bi-temporal
graph.search_semantic(query, k=10) -> list[Node]
graph.search_hybrid(query, k=10) -> list[Node]
graph.recent_episodes(window=Duration, type=NodeType | None) -> list[Episode]
```

**Slow reasoning (LLM-mediated, cost-typed)**:

```python
@cost($0.01)
graph.dialectic(question: str, peer_id: NodeId, depth=1) -> Answer

@cost($0.05)
graph.synthesize(topic: str, k_nodes=20) -> Synthesis

@cost($0.003)
graph.extract_observations(episode: Episode) -> list[Edge]  # deriver

@enforces_budget($1.00 per session)
```

### Background processes

- **Deriver** — async worker reading new episodes, extracting entities + edges, conflict-checking, temporally invalidating supersededs.
- **Dreamer** — periodic re-derivation over existing episodes when system is idle. Catches insights missed at ingestion.
- **Pruner** — *not* deletion. Compresses low-relevance subgraphs into single typed nodes with pointers back to the unrolled detail. Reversible.
- **Refresher** — periodic re-validation of high-importance facts (re-fetches market prices, re-checks documentation links).
- **Bridge auditor** — logs all cross-workspace queries; enforces bridge capability scopes.

---

## 4. Layer 2: The Workspace Coherence Layer

*This is the section to work out. The Graph is solved; the Coherence Layer is partly speculative. What's here is a design sketch with explicit open questions.*

### The problem

The Context Graph is the right substrate for *facts you might need someday*. It's the wrong substrate for *the agent's running understanding of what's going on right now in this workspace*.

An agent that walks into a workspace it's been in for weeks should feel like a teammate who's been around — they recognize context, remember recent patterns, know who tends to ask what, anticipate what's coming next. They don't query the graph every time they're addressed; they have a continuously updated understanding that gets sampled into individual LLM calls as needed.

This is **working memory + autobiographical context**, not retrieval-augmented generation. The architectural pattern is different, the lifetime is different, the granularity is different.

Penguin's Context Window Manager (CWM) operates one level below this: it's the token-budget allocator for a single LLM call (SYSTEM 10%, CONTEXT 30%, DIALOG 40%, SYSTEM_OUTPUT 20%). The Coherence Layer operates one level above CWM: it's the agent's standing model of the workspace, which then *gets sampled* by CWM into individual calls.

| Layer | Lifetime | Granularity | Scope |
|---|---|---|---|
| CWM (existing in Penguin) | Per LLM call | Tokens | Single message |
| Coherence Layer (new) | Per agent + workspace, weeks-to-months | Compressed episodes + schemata | Whole workspace |
| Context Graph | Permanent | Facts and relations | Cross-workspace via bridges |

### The architecture (sketch)

Per-agent, per-workspace state:

```python
class CoherenceState:
    workspace_id: WorkspaceId
    agent_id: AgentId
    
    # Three rings (memory hierarchy by access cost)
    active_attention: TokenWindow            # ~16-32K tokens, current focus
    warm_cache: list[CompressedEpisode]      # last N hours, semi-compressed
    cold_summaries: list[SchemaSummary]      # older, deeply compressed, graph-referenced
    
    # Extracted patterns
    schemata: list[Schema]                   # "how this team works"
                                             # examples: review style, channel purposes,
                                             # collaborator working hours, decision norms
    
    # Salience state
    salience_map: dict[Topic, SalienceScore] # what's "warm" and likely to matter soon
    
    # Reflective metadata
    last_refresh: DateTime
    decay_curve: DecayPolicy
    schema_extraction_cadence: Duration
```

### Compress / decompress dynamics

The Coherence Layer constantly compresses what's falling out of focus and decompresses what's becoming relevant. The dynamics are continuous, not request-driven.

**Compression triggers:**
- *Recency decay* — older episodes compress automatically on a configurable curve (default: exponential decay with half-life of one day for episode detail, one week for summary detail).
- *Topic shift* — when active attention moves to a new topic, related-to-old-topic items compress more aggressively.
- *Token pressure* — when the warm cache hits its budget, oldest items compress to make room.
- *Schema absorption* — when a pattern is observed N times, the individual episodes that exhibited the pattern compress to "instance of schema X."

**Decompression triggers:**
- *Topic activation* — a new message mentions a topic in cold storage. Decompress the related cold summaries, optionally fetch episodic detail from the graph.
- *Question requires it* — the agent is asked something whose answer needs specific old detail.
- *Schema invalidation* — if a schema's prediction fails, decompress the underlying episodes to re-examine.
- *Periodic reinforcement* — schemata get periodically tested against fresh episodes; failed predictions trigger decompression and review.

The compression mechanism itself is a separate problem. Two approaches worth thinking about:

1. **LLM-driven summarization** — straightforward, but expensive and lossy in unpredictable ways.
2. **Structural compression** — keep entities + relations but drop verbatim text. Reversible if linked back to graph. Cheaper.

A hybrid is likely correct: structural compression for episodes that hit the warm cache; LLM-driven summarization (with graph pointer) for cold storage; full episodic detail in the graph itself (never deleted).

### Schema extraction (the slow-but-important loop)

Schemata are extracted patterns about how the workspace operates. Examples:

- "This team always tests before merging."
- "Reviews from this collaborator focus on architecture; reviews from that one focus on naming."
- "Marketing channel goes quiet on Fridays."
- "When the CEO posts in the announcements channel, every leader replies within an hour."
- "Bugs filed by user X tend to be high-priority; bugs filed by user Y are usually feature requests."

These are not facts about the world (graph). They are *patterns about the workspace itself* — and they're what distinguish an experienced teammate from a new one.

The Dreamer process (already part of the Graph background workers) is the natural home for schema extraction. When the system is idle, the Dreamer reviews recent episodes against existing schemata and proposes new ones or refinements. Schemata that pass cross-model verification get promoted to the Coherence Layer; very high-confidence ones eventually get promoted to the Graph (where other agents can inherit them when they join the workspace).

### Cross-agent sharing

The Coherence Layer is per-agent by default (each agent has its own attention state). But some derived knowledge should be sharable:

- **Schemata** — once extracted with high confidence, promote to graph; other agents in the workspace inherit on initialization.
- **Salience maps** — partially shared. "These topics are hot right now" can be a workspace-level summary that all agents read on entry.
- **Episodes** — never compressed differently per agent; the underlying events are workspace-shared.

This is where Honcho's peer model gets interesting: an agent's view of *itself* in the workspace, including its own attention history, is also a kind of peer representation. The Coherence Layer for agent A includes A's peer-card-for-itself.

### Open research questions

This section is honest about what I don't yet know how to design:

1. **What's the right compression algorithm?** LLM summarization is expensive and lossy. Structural compression is cheap but loses nuance. Hybrid is likely correct but the cut-points need experimentation.
2. **How do you measure "coherence quality" empirically?** When is an agent's understanding of the workspace good vs. bad? There's no LoCoMo-style benchmark for this. Building one is a research project on its own.
3. **What's the right cadence for refresh?** Continuous re-evaluation is expensive. Batch updates miss real-time relevance. A predictive-coding model (refresh when prediction error exceeds threshold) is intellectually clean but operationally complex.
4. **How are schemata represented?** Natural language descriptions are easy to write but hard to operate on. Structured predicates are operable but hard to extract. Probably a mixed representation.
5. **Multi-agent coherence consistency** — if two agents in the same workspace have different schemata about the same pattern, who's right? Voting? Recency? Some agents being "trusted observers" for certain topics?
6. **Forgetting curves** — humans have well-studied decay curves (Ebbinghaus). Should agent coherence layers match human curves (to be more legible to human collaborators) or optimize differently?
7. **Cross-workspace coherence** — when an agent works in workspace A and is bridged into workspace B, does it carry coherence from A into B? Schemata from A applied to B might be misleading.
8. **Privacy and isolation** — the Coherence Layer accumulates patterns that humans might consider private (working hours, decision styles, response cadence). What's the consent model?

### Connection to existing systems

The Coherence Layer is closest in spirit to:

- **ACT-R's working memory + declarative memory** (Anderson et al.) — chunks, activation, decay.
- **Honcho's peer cards + dialectic supplement** — base context (who is this peer) + situational supplement (what matters now).
- **MemGPT's hierarchical paging** — but with attention dynamics, not just LRU.
- **Predictive coding architectures** (Friston, Clark) — relevance as prediction error, refresh as model update.

It is *not* the same as:

- Plain RAG (no continuous state).
- Vector DBs (those are storage, not attention).
- Penguin's existing CWM (one level below).
- The Context Graph (one level deeper, longer-lived).

This is genuinely new architectural territory. No existing system does the full thing.

---

## 5. Comparison tables

### Memory / context systems landscape

| System | Graph | Bi-temporal | Provenance | Multi-tenant | Coherence Layer | Reasoning | Open source |
|---|---|---|---|---|---|---|---|
| **Penguin-Link CG v1** | ✓ | ✓ | ✓ (Glass) | ✓ from line 1 | ✓ (sketch) | ✓ (dialectic) | ✓ MIT |
| Zep / Graphiti | ✓ | ✓ | timestamps only | partial (tenancy retrofit) | ✗ | ✗ (retrieval only) | ✓ MIT |
| Honcho | ✗ (vector) | ✗ | ✗ | ✓ workspaces | partial (peer card) | ✓ dialectic | ✓ MIT |
| Mem0 | ✓ hybrid | partial | ✗ | partial | ✗ | ✗ | ✓ |
| MemGPT / Letta | ✗ (tiered) | ✗ | ✗ | partial | partial (paging) | ✓ | ✓ Apache 2 |
| MemMachine | ✓ | ✗ | ✗ | ✗ | ✗ | ✓ | ✓ |
| ByteRover | ✗ (filesystem) | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ |
| GraphRAG (MS) | ✓ | ✗ | ✗ | ✗ | ✗ | ✓ communities | ✓ |
| A-Mem | ✓ | partial | ✗ | ✗ | ✗ | ✓ | ✓ |
| HippoRAG | ✓ | ✗ | ✗ | ✗ | ✗ | retrieval | ✓ |
| SYNAPSE | ✓ | ✗ | ✗ | ✗ | partial (spreading activation) | ✓ | research |
| HINDSIGHT | partial | ✗ | ✓ evidence-inference | ✗ | ✗ | ✓ | research |
| Cognee | ✓ (poly-store) | partial | ✗ | partial | ✗ | partial | ✓ Apache 2 |

The differentiation is concentrated in three columns: **provenance, multi-tenancy from line 1, Coherence Layer.** Everyone has the graph; few have any of these three; none have all three.

### Industry-scale knowledge platforms (the eventual competition)

| System | Domain | Coverage | Provenance | Network effect | Annual revenue |
|---|---|---|---|---|---|
| **Bloomberg Terminal** | Finance | 40+ years of data | Citations | Strong | ~$11B |
| AlphaSense | Market intel | Public + research | Source extraction | Growing | ~$200M ARR (est) |
| Palantir Foundry | Industrial / defense | Customer-owned | Audit trails | Per-customer | ~$2.5B |
| Sayari | Supply chain risk | Global corporate | Document-linked | Growing | Private |
| Dun & Bradstreet | B2B identity | 80+ years | Partial | Strong | ~$2.3B |
| Wikidata | General | 100M+ items | ✓ source-cited | Strong | (nonprofit) |
| Google Knowledge Graph | General | Billions | ✗ | (consumer) | (part of Google) |
| Diffbot | Web extraction | Open web | Citation links | Growing | Private |
| Penguin-Link CG | Workspace activity | Per-workspace | Glass-native | (designed in) | (future) |

The path to competing here is not "match Bloomberg's coverage." It is "build a substrate that compounds value through agent activity in specific verticals, with a provenance and federation model the incumbents can't match." Different game.

---

## 6. Integration with the rest of the stack

### Penguin
- **Local Penguin runs against a single-workspace, NetworkX-backed Context Graph.** Same API as the cloud version.
- **ITUV gates write episodic events** for every phase. Verify-phase failures become contested edges. Crystallized plans become persistent semantic structures.
- **Worktree parallelism** gets one Context Graph instance per worktree, with periodic cross-worktree synchronization (selective publishing of high-confidence edges).
- **Penguin's CWM** consumes from the agent's Coherence Layer to assemble individual call contexts. The CWM is the *sampler*; the Coherence Layer is the *source*.

### Link
- **Workspace = trust boundary = subgraph owner.** Same primitive across Link's existing data model and the Context Graph.
- **Channels, threads, tasks, files become episodic nodes** in the workspace's graph. The chat substrate is the graph's primary input.
- **Bridges = Slack-Connect-shaped cross-workspace primitives** also gate cross-graph access.
- **The Data Market trades workspace-owned subgraph slices** (with provenance preserved, PII stripped, alpha-signals redacted per the export policy).

### C\$
- **Cost-typed graph operations.** `@cost($0.01 per_query)` on every reasoning call.
- **Linear money for compute budgets** flowing through graph operations.
- **Sensors over graph changes** as a first-class language construct.
- **Cross-workspace queries pay** over x402 rails when bridge grants include pricing.

### Glass
- **Provenance is structural** on every node and edge. Glass annotations are the *type* of provenance, not metadata about it.
- **Trace export** to the Data Market is a one-line operation: `graph.export_traces(window, redaction=privacy_policy)`.
- **Cross-model verification** is recorded in `Provenance.verified_by`, queryable as part of the type.

### Logos
- **Spec/impl bonds for graph invariants.** Assertions about what edges must exist, what schemata must hold, what provenance is required for a fact to be acted upon.
- **Example:** `@logos.invariant "no trade executes against a TradeIdea whose provenance.verified_by is empty"` — at build time, the LLM bond-check confirms this holds in the implementation.

---

## 7. References to check out

Calibrated to the spec, not exhaustive. See `reading-list.md` for the broader topic.

### Foundational papers
- **Zep paper** (arXiv:2501.13956). The bi-temporal foundation. Required reading.
- **"Memory in the Age of AI Agents" survey** (arXiv:2512.13564). The field map.
- **"Causal Abstraction"** (JMLR 2025, vol 26, paper 23-0058). Formal foundation for provenance.
- **HINDSIGHT** (arXiv:2512.12818). Evidence-vs-inference separation. Most relevant to provenance design.

### Implementation references
- **Graphiti** (github.com/getzep/graphiti). MIT, currently the strongest open-source temporal context graph engine.
- **Honcho** (github.com/plastic-labs/honcho). MIT. The peer-centric reasoning model. Especially the CLAUDE.md and the deriver/dialectic/dreamer split.
- **Cognee** (github.com/topoteretes/cognee). Apache 2. Poly-store architecture; useful patterns for backend abstraction.
- **MemMachine paper** (arXiv:2604.04853). Current SOTA on LoCoMo.
- **Letta Filesystem result** (Dec 2025 blog post). The humbling counterpoint — filesystem + good tools sometimes beats fancy architectures.

### Cognitive-science foundations (for the Coherence Layer)
- **John R. Anderson, "How Can the Human Mind Occur in the Physical Universe?"** (Oxford, 2007). ACT-R architecture. Working memory + declarative memory + procedural memory dynamics.
- **Baddeley & Hitch's working memory model** (1974, revisited 2000s). Phonological loop, visuospatial sketchpad, central executive, episodic buffer.
- **Endel Tulving, "Episodic and Semantic Memory"** (1972). The original distinction.
- **Hermann Ebbinghaus, "Memory: A Contribution to Experimental Psychology"** (1885). Forgetting curves. Still relevant.
- **Karl Friston, "The Free-Energy Principle"** (2010 and follow-ups). Predictive coding as a unifying framework. Relevance-as-prediction-error.
- **Anders Ericsson, "Peak"** (popular but technically sound). Schemata and chunking in expertise.

### Industry / strategic references
- **Bloomberg's Terminal history and BQL documentation**. For "what does a successful proprietary knowledge platform look like" and BQL as a reference query language.
- **Wikidata's data model documentation**. The cleanest open knowledge graph.
- **Palantir Foundry documentation** (what's public). For "industrial-scale ontology management."
- **Sayari's product docs**. Closest to the supply-chain-graph use case we discussed.

---

## 8. Possible ideas (open exploration)

Speculative directions worth holding without committing to. Treat as a parking lot, not a roadmap.

### Coherence-Layer-as-product
The Coherence Layer might be a more interesting *standalone product* than the Graph. "Slack add-on: your AI teammate that actually remembers what happened" is a story consumers and small teams understand viscerally. The Graph is infrastructure; the Coherence Layer is a felt experience. Worth considering whether a Link extension demos this before the full Link platform is mature.

### Schema marketplace
Workspace operators might want to *import* well-tested schemata from other workspaces — "best practices for engineering review," "patterns for sales pipeline." These could be packaged, versioned, traded. A new dimension of the Data Market: not just traces, but *operational patterns*.

### Coherence diffs as collaboration primitive
When two agents in the same workspace disagree, expose the difference in their coherence states as a structured diff. Humans can audit which schemata disagreed, which episodes were weighted differently, which schemata had different confidence. The disagreement becomes a workspace-readable artifact.

### Forgetting as a feature, not a bug
Deliberate forgetting could be valuable. After a project ships, "compress everything about it; you don't need to actively understand it anymore but you can decompress if asked." This frees attention budget for current work without losing recall capability. The opposite of how every current system works (which is "remember as much as we can afford to").

### Sleep cycles
The Dreamer might run more aggressively during workspace inactivity. Schema consolidation, conflict resolution, predictive refresh. The cognitive analogy is direct: sleep is when consolidation happens in brains. A workspace's "off-hours" could be when its graph improves most.

### Coherence transfer between agents
When a new agent joins a workspace, it doesn't start from scratch. It can inherit a baseline coherence state from a designated "onboarder" agent in the workspace (one that has accumulated high-quality schemata and is trusted). Like a mentor relationship.

### Cross-workspace bridge as an economic primitive
Beyond pay-per-query, bridges could include reciprocity terms — workspace A grants access to its supplier subgraph in exchange for workspace B granting access to its market-condition subgraph. Pure barter on knowledge. Could be expressed in C\$ and settled programmatically.

### Coherence-as-evidence in markets
A trader's Coherence Layer at the moment of a decision is *evidence* of that decision's basis. For regulated industries (finance, healthcare), being able to produce the coherence state that led to a trade — with provenance, schemata, and salience map — is a powerful audit primitive. Could be a regulatory wedge.

### Public-workspace context graph as a free public good
The "public" workspace's graph is, by design, readable by anyone. Could be the open foundation for a new generation of knowledge graphs — Wikidata for the agent age. Provenance-typed, agent-contributed, federated by design. Probably won't compete with Wikidata on coverage but could be its operational complement.

### Sensor-as-API for cross-domain decision support
Once enough workspaces are running sensors over their domains, the union of sensors becomes a planetary-scale observation layer. A workspace could "subscribe" to "any sensor anywhere that fires on patents related to lithium chemistry." Cross-workspace sensor federation could be a feature in its own right.

---

## 9. Milestones

### Weekend MVP (May 17, 2026)
- Core types in Python (NetworkX backed) with workspace_id everywhere.
- Fast retrieval API.
- Simple deriver (extract entities from messages).
- Hello-world coherence: working_memory + warm_cache, no schema extraction yet.
- Demo: a Penguin agent that remembers a sequence of arbitrage observations and answers "what did we see on Tuesday in the Kalshi crypto markets?"

### Month 1 (end of June)
- Wrap Graphiti as the backend option; NetworkX stays for local.
- Bi-temporal queries.
- Provenance recorded on all writes.
- Honcho-style dialectic API for slow reasoning.
- Bridge primitive implemented (workspace-to-workspace grants).
- Basic schema extraction (no cross-agent sharing yet).

### Quarter 1 (end of August)
- Production-grade Coherence Layer with compress/decompress dynamics.
- Schema extraction with cross-agent promotion.
- Dreamer running as a real background process.
- Link integration: workspace-scoped graphs storing channel messages as episodes.
- First Data Wallet export of a Glass-annotated subgraph slice.

### End of year (December)
- Workspace coherence operational across the autopoietic Penguin's full activity.
- Data Market early access on Link.
- Public docs sufficient for external contributors.
- One paper or technical post on the Coherence Layer as a novel architectural pattern.

---

## 10. Closing note

The Context Graph is the substrate. The Coherence Layer is the felt experience. The Workspace boundary is the trust primitive. Provenance is the moat. The combination is what makes Penguin-Link different from every existing memory system and worth building.

The Graph is solved enough to start coding the weekend MVP. The Coherence Layer is partly speculative and rewards experimentation — there's a real chance that working on it surfaces a novel architectural pattern that becomes a citable contribution.

The discipline that holds everything together is the same one that holds C\$ together and that holds Penguin together: **declare the type, prove the property, audit the action**. Apply that to memory and you get a context graph that doesn't drift, doesn't lie about its sources, and doesn't expose what it isn't authorized to expose.

The next concrete artifact to produce: the weekend MVP code, with workspace_id on every row from the first commit.
