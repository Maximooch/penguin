# Penguin – Conversational Checkpointing & Branching Plan

## 1. Purpose & Scope

This plan describes how to add **checkpointing** and **branching** to Penguin’s conversation system while staying local‑only and JSON‑based.
Initial scope: **conversational memory level**.  Task‑level and code‑level checkpoints will build on the same principles later.

---

## 2. Design Goals

| Goal                               | Implication                                                                                                       |
| ---------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| *Complete lineage*                 | A checkpoint captures the **entire history**, even when the chat has been auto‑split into multiple session files. |
| *Zero external DB*                 | Re‑use Penguin’s JSON file model; extend `session_index.json` only.                                               |
| *Cheap storage*                    | One compact JSON snapshot per checkpoint/branch.                                                                  |
| *UI first*                         | Users create, name, browse, and fork checkpoints via simple controls.                                             |
| *Orthogonal to auto‑continuations* | Branches can themselves split into child session files without breaking.                                          |

---

## 3. Data Model Extensions

```jsonc
// Example checkpoint session JSON (trimmed)
{
  "id": "session_20250525T153200_4b9a",
  "created_at": "2025‑05‑25T15:32:00‑05:00",
  "metadata": {
    "title": "Before alternative approach",
    "continued_from": "session_root",
    "branch_point": "msg_5f2e1d3c"
  },
  "messages": [ /* messages 1‑N up to branch point */ ]
}
```

* **`continued_from`** & **`continued_to`** now accept **lists** ⇒ multiple children.
* Optional `lineage` array (root…self) can be stored in metadata for debugging.

---

## 4. Collecting Full Lineage

```python
def collect_lineage(self, session_id: str) -> list[str]:
    """Return [root … session_id] following 'continued_from'."""
    chain, current = [], session_id
    while current:
        chain.insert(0, current)
        current = self.session_index.get(current, {}).get("continued_from")
    return chain
```

*Lives in `SessionManager` (≈ 10 LOC).*
No disk I/O—reads lightweight index only.

---

## 5. Building a Flattened Snapshot

```python
def build_flat_snapshot(self, tail: Session, *, upto_msg: str | None = None) -> Session:
    lineage = self.collect_lineage(tail.id)
    merged = Session(metadata={
        "branched_from": tail.id,
        "lineage": lineage,
        "branch_point": upto_msg,
    })
    for sid in lineage:
        src = self.load_session(sid)           # cached → cheap
        for m in src.messages:
            merged.add_message(m.copy())
            if sid == tail.id and m.id == upto_msg:
                break
    merged.dedupe_header_messages()
    return merged
```

Creates one **self‑contained** Session containing every message up to the branch point.

---

## 6. ConversationManager Touch‑Points

1. **`create_snapshot()` / `branch_from_snapshot()`**
   *Replace* payload generation with the flattened snapshot:

   ```python
   snap = session_manager.build_flat_snapshot(self.conversation.session)
   payload = json.dumps(snap.to_dict(), ensure_ascii=False)
   ```
2. **`branch_at(session_id, message_id)`** (≈ 20 LOC)
   Loads target session, calls `build_flat_snapshot()`, persists new branch, sets active.

---

## 7. UI Affordances

| Feature                | UX behaviour                                                            |
| ---------------------- | ----------------------------------------------------------------------- |
| **Save Checkpoint**    | Button writes snapshot; ask for optional name.                          |
| **Branch from Here**   | Context‑menu on any message or checkpoint. Opens new tab/thread.        |
| **Conversation Tree**  | Sidebar shows root→branches hierarchy (expandable nodes).               |
| **Restore / Navigate** | Click checkpoint to load it read‑only; new messages fork automatically. |
| **Delete Branch**      | Disabled if branch has children; else removes JSON + index entry.       |

---

## 8. Edge‑Case Handling

* **Branching root** → lineage length 1; trivial.
* **Deleting parents** → safe; each snapshot is self‑contained.
* **Auto‑continuations inside a branch** → existing logic untouched; still uses `continued_from` pointer.
* **Merging branches** → out of scope for v1; lineage metadata enables future diff/merge tool.

---

## 9. Roll‑out Steps

1. **SessionManager helpers** (`collect_lineage`, `build_flat_snapshot`).
2. **ConversationManager** modifications + `branch_at` API.
3. **Extend `session_index.json` schema** (allow lists in `continued_to`).
4. **UI:** checkpoint button, branch action, tree sidebar (MVP in CLI → GUI).
5. **QA:**

   * Unit tests for lineage merge edge cases.
   * Stress‑test 10k‑message chat split across >10 files, multiple branches.
6. **Docs & Examples**: Update README, add demo GIF.

---

## 10. Future Work

* **Task‑level checkpoints** → snapshot task graph & agent memory.
* **Code‑level checkpoints** → Git‑based; mirror RooCode’s workspace commits.
* **Automated branching heuristics** (agent decides to fork paths).
* **Diff/Merge UI** to reconcile divergent branches.
