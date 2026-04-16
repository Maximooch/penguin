## Payload limits

Prevent blocking storage writes and runaway persisted size

---

### Summary

Large payloads (base64 images, terminal buffers) are currently persisted inside key-value stores:

- app/web: `localStorage` (sync, blocks the main thread)

We’ll introduce size-aware persistence policies plus a dedicated blob storage strategy for large/binary data. Prompt/history state will persist only lightweight references to blobs and load them on demand.

---

### Goals

- Stop persisting image `dataUrl` blobs inside web `localStorage`
- Store image payloads out-of-band (blob store) and load lazily when needed (e.g. when restoring a history item)
- Prevent terminal buffer persistence from exceeding safe size limits
- Keep persistence behavior predictable across app/web surfaces
- Provide escape hatches via flags and per-key size caps

---

### Non-goals

- Cross-device sync of images or terminal buffers
- Lossless persistence of full terminal scrollback on web
- Perfect blob deduplication or a complex reference-counting system on day one

---

### Current state

- `packages/app/src/utils/persist.ts` uses `localStorage` (sync) for persisted state.
- Prompt history persists under `Persist.global("prompt-history")` (`packages/app/src/components/prompt-input.tsx`) and can include image parts (`dataUrl`).
- Prompt draft persistence uses `packages/app/src/context/prompt.tsx` and can also include image parts (`dataUrl`).
- Terminal buffer is serialized in `packages/app/src/components/terminal.tsx` and persisted in `packages/app/src/context/terminal.tsx`.

---

### Proposed approach

#### 1) Add per-key persistence policies (KV store guardrails)

In `packages/app/src/utils/persist.ts`, add policy hooks for each persisted key:

- `warnBytes` (soft warning threshold)
- `maxBytes` (hard cap)
- `transformIn` / `transformOut` for lossy persistence (e.g. strip or refactor fields)
- `onOversize` strategy: `drop`, `truncate`, or `migrateToBlobRef`

This protects app/web persistence paths where `localStorage` is synchronous and expensive for oversized values.

#### 2) Add a dedicated blob store for large data

Introduce a small blob-store abstraction used by the app layer:

- backend: IndexedDB or another non-`localStorage` store keyed by blob `id`

Store _references_ to blobs inside the persisted JSON instead of the blob contents.

#### 3) Persist image parts as references (not base64 payloads)

Update the prompt image model so the in-memory shape can still use a `dataUrl` for UI, but the persisted representation is reference-based.

Suggested approach:

- Keep `ImageAttachmentPart` with:
  - required: `id`, `filename`, `mime`
  - optional/ephemeral: `dataUrl?: string`
  - new: `blobID?: string` (or `ref: string`)

Persistence rules:

- When writing persisted prompt/history state:
  - ensure each image part is stored in blob store (`blobID`)
  - persist only metadata + `blobID` (no `dataUrl`)
- When reading persisted prompt/history state:
  - do not eagerly load blob payloads
  - hydrate `dataUrl` only when needed:
    - when applying a history entry into the editor
    - before submission (ensure all image parts have usable `dataUrl`)
    - when rendering an attachment preview, if required

---

### Phased implementation steps

1. Add guardrails in `persist.ts`

- Implement size estimation in `packages/app/src/utils/persist.ts` using `TextEncoder` byte length on JSON strings.
- Add a policy registry keyed by persist name (e.g. `"prompt-history"`, `"prompt"`, `"terminal"`).
- Add a feature flag (e.g. `persist.payloadLimits`) to enable enforcement gradually.

2. Add blob-store abstraction + platform hooks

- Add a new app-level module (e.g. `packages/app/src/utils/blob.ts`) defining:
  - `put(id, bytes|Blob)`
  - `get(id)`
  - `remove(id)`
- Extend the `Platform` interface (`packages/app/src/context/platform.tsx`) with optional blob methods, or provide a default implementation for current app/web surfaces.

3. Update prompt history + prompt draft persistence to use blob refs

- Update prompt/history serialization paths to ensure image parts are stored as blob refs:
  - Prompt history: `packages/app/src/components/prompt-input.tsx`
  - Prompt draft: `packages/app/src/context/prompt.tsx`
- Ensure “apply history prompt” hydrates image blobs only when applying the prompt (not during background load).

4. Add migration for legacy persisted entries

- On read, detect legacy persisted image parts that include `dataUrl`.
- If a `dataUrl` is found:
  - write it into the blob store (convert dataUrl → bytes)
  - replace persisted payload with `{ blobID, filename, mime, id }` only
  - re-save the reduced version
- If migration fails (missing permissions, quota, etc.), fall back to:
  - keep the prompt entry but drop the image payload and mark as unavailable

5. Fix terminal persistence (bounded snapshot)

- In `packages/app/src/context/terminal.tsx`, persist only:
  - last `maxLines` and/or
  - last `maxBytes` of combined text
- In `packages/app/src/components/terminal.tsx`, keep the full in-memory buffer unchanged.

6. Add basic blob lifecycle cleanup
   To avoid “blob directory grows forever”, add one of:

- TTL-based cleanup: store `lastAccessed` per blob and delete blobs older than N days
- Reference scan cleanup: periodically scan prompt-history + prompt drafts, build a set of referenced `blobID`s, and delete unreferenced blobs

Start with TTL-based cleanup (simpler, fewer cross-store dependencies), then consider scan-based cleanup if needed.

---

### Data migration / backward compatibility

- KV store data:
  - policies should be tolerant of missing fields (e.g. `dataUrl` missing)
- Image parts:
  - treat missing `dataUrl` as “not hydrated yet”
  - treat missing `blobID` (legacy) as “not persisted” or “needs migration”

---

### Risk + mitigations

- Risk: blob store is unavailable (IndexedDB disabled or storage quota issues).
  - Mitigation: keep base state functional; persist prompts without image payloads and show a clear placeholder.
- Risk: lazy hydration introduces edge cases when submitting.
  - Mitigation: add a pre-submit “ensure images hydrated” step; if hydration fails, block submission with a clear error or submit without images.
- Risk: dataUrl→bytes conversion cost during migration.
  - Mitigation: migrate incrementally (only when reading an entry) and/or use `requestIdleCallback` on web.
- Risk: blob cleanup deletes blobs still needed.
  - Mitigation: TTL default should be conservative; scan-based cleanup should only delete blobs unreferenced by current persisted state.

---

### Validation plan

- Unit-level:
  - size estimation + policy enforcement in `persist.ts`
  - blob store put/get/remove round trips for the chosen backend
- Manual scenarios:
  - attach multiple images, reload, and confirm:
    - persisted key-value state does not balloon
    - images can be restored when selecting history items
  - open terminal with large output and confirm reload restores bounded snapshot quickly
  - confirm prompt draft persistence still works in `packages/app/src/context/prompt.tsx`

---

### Rollout plan

- Phase 1: ship with `persist.payloadLimits` off; log oversize detections in dev.
- Phase 2: enable image blob refs behind `persist.imageBlobs`.
- Phase 3: enable terminal truncation and enforce hard caps for known hot keys.
- Phase 4: enable blob cleanup behind `persist.blobGc` (TTL first).
- Provide quick kill switches by disabling each flag independently.

---

### Open questions

- What should the canonical persisted image schema be (`blobID` field name, placeholder shape, etc.)?
- Web/app implementation detail:
  - do we store `Blob` directly in IndexedDB, or store base64 strings?
- Should prompt-history images be retained indefinitely, or only for the last `MAX_HISTORY` entries?
