### “Link” — High-Level Product Snapshot

| Dimension             | What It Is                                                                                                                                               | Why It Matters                                                                                        |
| --------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| **Core Identity**     | **All-in-one operational cockpit** that merges Slack-style chat, Notion-lite project management, and a control panel for autonomous AI “Penguin” agents. | Stops the SaaS pinball game—one window for humans *and* AIs to collaborate.                           |
| **Primary Users**     | Solo builders → 20-person tech teams that juggle code, content, and ops workstreams.                                                                     | Early-stage startups can’t afford a tool zoo or an ML-ops team.                                       |
| **North-Star Metric** | **Time-to-Task-Done** (human+AI) < **5 min** for common workflows (code review, research summary, marketing copy draft).                                 | The product wins only if it’s *measurably* faster than “open Slack + open Jira + paste into ChatGPT”. |

---

#### 1. Interaction Layers

1. **Chat Threads**
   *Slack-like channels & DMs* where messages can be:

   * plain human text
   * `/penguin …` slash-commands that spawn an AI task
   * live streaming deltas from an agent

2. **Tasks & Kanban**
   Lightweight board (columns = Backlog → In-Progress → Review → Done).
   Cards can be assigned to **humans, agents, or both**; sub-tasks show real-time agent progress.

3. **Agent Control Center**

   * **Create / Clone** Penguin presets (LLM, tools, memory limits).
   * **Governance**: throttle, pause, or sandbox an agent.
   * **Telemetry**: token usage, success rate, last error stack trace.

4. **Knowledge Hub (optional add-on)**
   Auto-organized artefacts (docs, code snippets, media) produced by agents, versioned and searchable.

---

#### 2. Data & Architecture Cheat-Sheet

| Data Type                        | Store                            | Access Pattern  |
| -------------------------------- | -------------------------------- | --------------- |
| Real-time chat                   | PostgreSQL (row) + Redis pub/sub | <200 ms fan-out |
| Project metadata                 | PostgreSQL JSONB                 | transactional   |
| Vector embeddings (agent memory) | Qdrant                           | cosine search   |
| Artefacts (files)                | S3-compatible object store       | presigned URLs  |

---

#### 3. Key Differentiators vs. “Slack + Asana + GPT”

| Lever                             | Competitive Edge                                                                           |
| --------------------------------- | ------------------------------------------------------------------------------------------ |
| **Unified context window**        | Agents read channel history *and* project data without copy-pasta.                         |
| **Role-based guardrails**         | Fine-grained ACLs for what each Penguin can touch (repos, APIs, docs).                     |
| **Zero-code agent orchestration** | Non-dev founders can chain agents via drag-drop DAG, yet power users still get YAML / CLI. |
| **Cost observability**            | Built-in token+GPU cost dashboard; alert when burn-rate > budget.                          |

---

#### 4. Illustrative Workflow

> *Maximus needs a marketing blog post about Link’s new AI feature.*

1. In **#marketing** channel, he types `/penguin generate blog_post launch_ai`.
2. Task card appears in **Kanban → In-Progress**, assigned to **Penguin-Copywriter**.
3. Agent streams outline → full draft; Maximus comments inline.
4. Drag card to **Review**; human teammate edits, toggles “Send to Medium”.
5. Post-mortem stats auto-logged: 2.3 k tokens, \$0.07 cost, 8 min wall-clock.

---

#### 5. MVP vs. Future Roadmap

| Stage            | Must-Have                                                             | Nice-to-Have (post-Seed)                                                           |
| ---------------- | --------------------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| **MVP (6 mo)**   | Chat, basic Kanban, one LLM backend, slash-command tasks, telemetry   | Calendar integration, fine-tuned vision model for screenshot QA, agent marketplace |
| **v1.5 (12 mo)** | Declarative agent workflows (DAG), GitHub PR bot, multi-vector memory | On-prem deployment, federated RAG across user docs, pay-as-you-go GPU burst        |

---

### Bottom Line

Link’s promise is **“one tab to run the company”**—human conversation, structured project tracking, and AI labor pooled under tight governance. If it doesn’t cut **Time-to-Task-Done** by an order of magnitude, kill the feature or rethink it.
