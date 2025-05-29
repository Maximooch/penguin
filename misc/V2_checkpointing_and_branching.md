# Penguin – Checkpointing & Branching Plan (v2.1)

> **Goal:** Give every conversation turn a “⌘ Z on steroids” rollback / branch feature while staying local‑only, fast, and cheap.

---

## 1. Scope & Vision
* **Planes captured** every turn:
  | Plane | Artifact | Format | Δ‑size/turn |
  |-------|----------|--------|-------------|
  | Conversation | `Message` object | append to session JSON | ≈ 1 KB |
  | Task / agent state | `TaskGraph` snapshot | `snapshots/msg_<ID>.json.gz` | ≈ 10 KB |
  | Code workspace | pre‑ & post‑image commits | Git (branch `penguin/<session>`) | ≈ 5 KB (delta) |
* Rollback → truncate chat + restore task JSON + `git reset --hard` to pre‑image.  
* Branch → flatten snapshot → start new lineage on its own branch.

---

## 2. Core Design Principles
| Principle | Rationale |
|-----------|-----------|
| **Zero user effort** | Auto‑checkpoint every message; manual checkpoints optional. |
| **Complete lineage** | Flatten ancestors so a checkpoint is self‑contained even after auto‑splits. |
| **Async, non‑blocking** | Checkpointing must never freeze the chat UI. |
| **Cheap storage** | Text deltas + gzip + retention GC keep footprint tiny. |
| **Graceful degradation** | If workspace isn’t a git repo → capture only chat + tasks and warn. |

---

## 3. Architecture Overview
```
ConversationManager.add_message()
  ├─ append Message JSON  (sync, O(1 KB))
  ├─ enqueue Task snapshot   (async → worker)
  └─ enqueue Git checkpoints (async → worker)
Background workers
  ├─ TaskWorker  : snapshot/restore *.json.gz
  └─ GitWorker   : commit pre/post if repo dirty, run `git gc --auto`
```
Workers run in a thread‑pool (or asyncio) so the send‑message path remains <2 ms.

---

## 4. Implementation Road‑map
### Phase 1 — Conversation plane only *(2 weeks)*
1. `SessionManager.collect_lineage()` & `build_flat_snapshot()` (done).
2. Auto‑checkpoint list in `session_index.json` (keep first 24 h).
3. UI: ↩︎ Rollback & 🌿 Branch icons beside every bubble.

### Phase 2 — Task plane *(2 weeks)*
1. `TaskManager.snapshot(msg_id)` → gzip write in `system/tasks/snapshots/`.
2. `TaskManager.restore(msg_id)` on rollback/branch.
3. Retention policy: keep‑all 24 h → every 10th up to 7 days → prune.

### Phase 3 — Code plane *(3 weeks)*
1. `WorkspaceManager` wraps GitPython; ensure branch `penguin/<session>`.
2. `checkpoint_pre/post(msg_id)` commits **only if repo dirty**.
3. Git GC cron, LFS for large binaries.
4. UI diff modal (`git diff pre..post`).

---

## 5. Performance & Storage
| Concern | Mitigation |
|---------|-----------|
| **Git commit latency** | Run in background worker; skip if no changes; batch rapid‑fire edits into single commit. |
| **Disk churn on NFS/slow SSD** | Config knob `checkpoint.frequency`; default = 1; CLI `set freq 5` for heavy chats. |
| **Repo bloat** | Weekly `git gc`; prune branches inactive >30 days; user‑configurable. |
| **Task snapshot size** | gzip (≈ 3× smaller); retention GC. |

---

## 6. Config File (`penguin.yaml`)
```yaml
checkpointing:
  enabled: true
  frequency: 1          # every N messages
  planes:
    conversation: true
    tasks: true
    code: true
  retention:
    keep_all_hours: 24  # after that…
    keep_every_nth: 10  # keep every 10th until max_age_days
    max_age_days: 30
```

---

## 7. Data‑Model Snippets
### Session JSON extension
```jsonc
{
  "metadata": {
    "continued_from": ["session_root"],
    "continued_to": ["session_childA", "session_childB"],
    "lineage": ["root", "…", "self"],
    "branch_point": "msg_5f2e1d3c",
    "auto": true  // auto‑checkpoint
  }
}
```

### Task snapshot header
```jsonc
{
  "msg_id": "msg_abc123",
  "timestamp": "2025‑05‑26T18:42:01‑05:00",
  "workspace": "~/projects/demo",
  "graph": { … }
}
```

---

## 8. UI Summary (MVP)
* **Chat bubble hover** → buttons ↩︎ Rollback | 🌿 Branch | ⭐ Name.
* **Sidebar** → branch tree; click = open, right‑click = delete/rename.
* **Rollback modal** shows code diff (if code plane enabled) + confirm.
* **Settings** → toggle planes, set frequency, view disk usage.

---

## 9. Edge‑Case Behaviour
| Scenario | Result |
|----------|--------|
| Human edits between AI turns | Pre‑image commit captures current state; rollback drops human edits (expected). |
| Workspace missing git | Penguin `git init`; on failure disables code plane, warns once. |
| Parallel chat branches | Each branch = its own git branch + snapshot path. |
| Storage cap exceeded | Oldest auto checkpoints pruned respecting retention rules. |

---

## 10. Future Work
* Auto‑branch heuristics (LLM proposes alt‑path → user accepts).
* Diff/Merge UI across branches.
* Export bundle (chat + snapshots + repo) for sharing/re‑import.
* Remote sync plugin for cloud backup / team collaboration.
