## Link Notifications System — Plan

### Purpose
Design a Slack/Discord-grade notifications platform for Link that is simple to ship (1/3 complexity) yet powerful (3× capability). Optimize for high-signal, low-noise alerts that shorten Time-to-Task-Done.

### Goals
- Deliver actionable, real-time in-app notifications with low latency.
- Support mentions, replies, task updates, agent events, and system alerts.
- Provide robust user preferences (global/workspace/channel/thread/keywords) with DND/snooze.
- Guarantee durability, deduplication, idempotency, and privacy boundaries.
- Ship early with minimal infra (Postgres + Redis) and evolve to Kafka only if needed.

### Non-Goals (MVP)
- Mobile push, email digests, and 3rd-party webhooks (planned in phases).
- Complex read-receipts semantics (stick to per-user read state; no cross-user receipts).

---

## Product & UX Principles (inspired by Slack/Discord)

- **Signal first**: Default to mentions and direct replies. Allow opt-in to all messages per channel.
- **Per-scope controls**: Global → workspace → channel → thread overrides; server/channel model mirrors Discord.
- **DND / Snooze**: Global and per-workspace; auto-resume; respect working hours.
- **Keyword highlights**: Slack-style custom words/regex (short list) with rate-limited pings.
- **Thread smartness**: Bundle new thread replies; single notification until the thread is viewed.
- **Summaries over spam**: Group rapid-fire agent updates; summarize every N seconds or on state change.
- **Presence-aware**: Escalate to out-of-app channels only when user is inactive (future).
- **Respect context**: Deep-link to the exact message/task; preview the relevant delta.

---

## Notification Taxonomy

- **Conversation**: mention (@user), reply-in-thread, keyword match, channel DM.
- **Project/Task**: assignment, status change, comment mention, due/reminder.
- **Agent**: task progress milestone, completion, error/failure, escalation request.
- **System**: permission request, role change, workspace invite, billing/limit alerts.
- **Digest**: periodic bundle per channel/thread/project (optional, phase 2+).

Each notification has: `type`, `actor`, `subject`, `context_ref` (message/task/thread IDs), `priority`, `visibility`, `snoozeable`, `ephemeral` flag.

---

## Delivery Channels

1) **In-App Real-Time**: WebSocket fan-out with counters/badges and inbox list.
2) **Out-of-App** (future phases):
   - Email digests (daily/weekly) with thread bundles
   - Mobile/web push (FCM/APNs via a gateway)
   - Webhooks to external systems (Slack bridge, custom endpoints)

---

## Architecture Overview

```mermaid
flowchart LR
  subgraph Producers
    MSG[Messages] --> EVT
    TASK[Tasks] --> EVT
    AGT[Agent Events] --> EVT
    SYS[System Events] --> EVT
  end

  EVT[Event Outbox (Postgres)] --> BUS
  BUS[Stream (Redis Streams)] --> RTE[Router/Normalizer]
  RTE --> PREF[Preference Engine]
  PREF --> FAN[Fanout Worker]
  FAN --> WS[WebSocket Hub]
  FAN --> PERS[(Postgres Notifications)]
  FAN --> OOB[Out-of-Band Queue]

  WS --> CLIENT[Clients]
  OOB --> EMAIL[Email/Push/Webhooks]
```

### Rationale (3× capability, 1/3 complexity)
- **Event Outbox**: Use transactional outbox table in Postgres; simple, reliable.
- **Redis Streams**: Lightweight stream with replay; no early Kafka dependency.
- **One Router**: Normalize all producers to a single `NormalizedEvent` schema.
- **Single Preference Engine**: Deterministic filter for who gets what, how, and when.
- **Fanout**: Write durable `Notification` rows + emit WS events; schedule OOB jobs later.

---

## Data Model (Postgres)

```sql
-- Source events (immutable, append-only)
create table notification_events (
  id uuid primary key,
  occurred_at timestamptz not null,
  event_type text not null, -- e.g., message.created, task.assigned
  workspace_id uuid not null,
  actor_id uuid not null,
  payload jsonb not null,
  dedupe_key text, -- opt-in for idempotency at source
  created_at timestamptz default now()
);

-- Normalized, user-scoped notifications (durable)
create table notifications (
  id uuid primary key,
  user_id uuid not null,
  workspace_id uuid not null,
  type text not null, -- mention, reply, task_update, agent_error, system
  priority smallint not null default 5, -- 1=highest
  context jsonb not null, -- refs: message_id, thread_id, task_id, url
  title text not null,
  subtitle text,
  preview text,
  status text not null default 'pending', -- pending|delivered|read|dismissed
  delivery_channels text[] not null default array['in_app'],
  ephemeral boolean not null default false,
  created_at timestamptz default now(),
  delivered_at timestamptz,
  read_at timestamptz,
  dismissed_at timestamptz
);

-- Per-user settings with hierarchical scopes
create table notification_preferences (
  id uuid primary key,
  user_id uuid not null,
  scope_type text not null, -- global|workspace|channel|thread|project
  scope_id uuid, -- null for global
  setting jsonb not null, -- see Preference JSON below
  updated_at timestamptz default now(),
  unique (user_id, scope_type, scope_id)
);

-- Delivery attempts (OOB channels)
create table notification_delivery_attempts (
  id uuid primary key,
  notification_id uuid not null references notifications(id),
  channel text not null, -- email|push|webhook
  status text not null, -- queued|sent|failed
  attempt_no int not null default 1,
  last_error text,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);
```

### Preference JSON (shape)
```json
{
  "mode": "mentions_only|all|mute|custom",
  "keywords": ["urgent", "oncall"],
  "dnd": { "enabled": true, "start": "22:00", "end": "07:00", "timezone": "UTC" },
  "snooze_until": null,
  "agent_events": { "bundle": true, "min_interval_ms": 5000 },
  "channels": { "in_app": true, "email": false, "push": false },
  "escalation": { "inactive_minutes": 30, "fallback_channel": "email" }
}
```

---

## Event Schema (Normalized)

```typescript
type NormalizedEvent = {
  id: string;
  occurredAt: string;
  type:
    | 'message.created'
    | 'message.mentioned'
    | 'thread.replied'
    | 'task.assigned'
    | 'task.status_changed'
    | 'agent.progress'
    | 'agent.error'
    | 'system.alert';
  workspaceId: string;
  actor: { id: string; type: 'user' | 'agent' | 'system'; name?: string; avatarUrl?: string };
  targets: string[]; // userIds potentially affected
  context: {
    channelId?: string;
    threadId?: string;
    messageId?: string;
    projectId?: string;
    taskId?: string;
    url?: string;
  };
  text?: string; // preview text
  priority?: 1 | 2 | 3 | 4 | 5;
  dedupeKey?: string;
};
```

---

## API Surface (tRPC + WebSocket)

### tRPC Procedures
- `notifications.list({ cursor?, limit?, filter? })` → paginated inbox
- `notifications.unreadCount()` → number
- `notifications.markRead({ id })` / `markAllRead({ scope? })`
- `notifications.dismiss({ id })`
- `preferences.get({ scopeType, scopeId? })`
- `preferences.set({ scopeType, scopeId?, setting })`
- `keywords.list|set`, `dnd.get|set`, `snooze.set|clear`

### WebSocket Events
- `notification:new` → minimal payload for badge/inbox insert
- `notification:update` → status transitions (delivered/read/dismissed)
- `notification:count` → unread badge updates

Payload example:
```json
{
  "id": "notif_123",
  "type": "mention",
  "title": "Ada mentioned you in #backend",
  "preview": "@you can you review PR #42?",
  "context": { "channelId": "ch_1", "threadId": "th_9", "messageId": "msg_7", "url": "/c/ch_1/t/th_9?m=msg_7" },
  "createdAt": "2025-09-28T10:10:00Z"
}
```

---

## Core Services

- **Event Outbox Writer**: Within existing write paths (messages/tasks/agents), write a row to `notification_events` inside the same DB tx. Use a background poller to push to Redis Streams.
- **Router/Normalizer**: Convert provider-specific shapes into `NormalizedEvent`; compute potential targets.
- **Preference Engine**: Resolve effective preferences by merging scopes: `global < workspace < channel < thread`. Evaluate keyword hits, DND, snooze, and mute rules.
- **Fanout Worker**: For each recipient, create `notifications` row, emit WS event, schedule OOB if applicable. Enforce dedupe via `(user_id, dedupe_key)` unique optional index.
- **Aggregator (Agent events)**: Collate multiple `agent.progress` events within `min_interval_ms`; emit a summarized notification on milestone or interval.

---

## Relevance & Noise Controls

- **Thread bundling**: First event creates a notification; subsequent events in the same thread upgrade the existing row’s preview and increment a counter until the thread is viewed.
- **Keyword throttle**: Per-user sliding window for keyword hits; collapse duplicates.
- **Agent rate caps**: Per-agent, per-user caps with backoff; hard-stop for misbehaving agents; surface a single “agent noisy” alert with mute shortcut.
- **Visit resets**: Viewing a thread or task marks related pending notifications as delivered/read.

---

## Performance, Reliability, and Semantics

- **Latency targets (in-app)**: P95 ≤ 150 ms from write to WS emit; P99 ≤ 300 ms.
- **Durability**: All delivered notifications persist in Postgres; WS is best-effort but followed by durable fetch.
- **Idempotency**: Use `dedupe_key` + unique constraint to avoid duplicates; Router must be retry-safe.
- **Ordering**: Per-user ordering by `created_at`; do not guarantee cross-user global order.
- **Backpressure**: Use Redis Streams consumer groups with maxlen and dead-letter list; shed load on low-priority types first.

---

## Observability & Alerts

Metrics (Prometheus labels by `type`, `workspace`, `channel`):
- **Delivery**: `notif_emitted_total`, `notif_persisted_total`, `notif_ws_fanout_ms` (histogram)
- **Inbox**: `notif_unread_gauge`, `notif_backlog_gauge`
- **Quality**: `notif_dropped_total`, `notif_dedup_hits_total`, `notif_bundle_events_total`
- **Engine**: `pref_eval_ms`, `router_lag_ms`, `redis_stream_lag_ms`
- **Errors**: `oob_send_fail_total`, `ws_send_fail_total`

Alerts:
- WS fanout P95 > 300 ms 5m
- Dropped > 0.1% 10m
- Stream lag > 3s 5m
- Dedup hits spike (spam) > threshold

---

## Security & Privacy

- **Scope enforcement**: Only notify users with permission to view `context_ref` objects.
- **Redaction**: Strip sensitive payload fields; include minimal preview; fetch full details on-demand.
- **Tenant isolation**: Workspace scoping on every query; index on `(user_id, workspace_id)`.
- **Audit**: Log preference changes and OOB deliveries with reasons.

---

## Rollout Plan

### Phase 1 (MVP)
- In-app notifications: mentions, thread replies, task assignment/status.
- Global + workspace preferences; DND + snooze; unread counter.
- Redis Streams pipeline; WS fanout; durable inbox list.

### Phase 2
- Agent notifications with bundling; channel-level preferences; keyword highlights.
- Email daily digest; per-channel mute; thread bundling UX.

### Phase 3
- Webhooks for external sinks; Slack bridge bot (optional); server-wide keyword policies.
- Mobile/web push with presence-aware escalation.

### Phase 4
- Advanced admin policies (mandatory alerts, rate caps per workspace); analytics dashboard.

---

## UX Details (Parity Inspirations)

- **Discord-like per-channel modes**: All messages | Mentions only | Nothing.
- **Slack-like keywords**: Short list with case-insensitive match; phrase support; toggle per channel.
- **Mute/Unmute**: Channel/project/thread; duration-based snooze.
- **Badges**: Workspace-level unread, channel-level unread, mentions pill.
- **Quick actions**: From notification: Mark read, Mute thread, Go to message, Assign task.

---

## Example Preference Resolution

```text
effective = merge(global, workspace[wid], channel[cid], thread[tid])
if effective.mode == mute: drop
if in_dnd_window(effective): defer
if keyword_hit and not allowed(effective): drop
if type == agent.progress and effective.agent_events.bundle: aggregate
else: emit
```

---

## Example tRPC Snippets (illustrative)

```ts
const notificationsRouter = router({
  list: publicProcedure.input(z.object({ cursor: z.string().optional(), limit: z.number().min(1).max(100).default(20), filter: z.object({ type: z.string().optional() }).optional() }))
    .query(({ ctx, input }) => ctx.db.notifications.list(ctx.userId, input)),
  unreadCount: publicProcedure.query(({ ctx }) => ctx.db.notifications.unreadCount(ctx.userId)),
  markRead: publicProcedure.input(z.object({ id: z.string() })).mutation(({ ctx, input }) => ctx.db.notifications.markRead(ctx.userId, input.id)),
  markAllRead: publicProcedure.input(z.object({ scopeType: z.string().optional(), scopeId: z.string().optional() })).mutation(({ ctx, input }) => ctx.db.notifications.markAllRead(ctx.userId, input)),
});
```

---

## Risks & Mitigations

- **Agent spam**: Bundle + cap + mute shortcuts; anomaly alerts.
- **Preference complexity**: Start with global/workspace; add channel/thread iteratively.
- **Infra sprawl**: Stick to Postgres + Redis Streams initially.
- **Ordering illusions**: Communicate per-user order only; deep-link to canonical objects.

---

## Open Questions

1) Should keyword highlights support regex or only plain phrases initially?
2) What is the desired default mode per new channel (mentions-only vs all)?
3) Do we need workspace-admin enforced alerts (e.g., billing) that bypass DND?
4) What max bundling window for agent updates balances freshness vs noise (3–10s)?
5) Do we allow per-device push toggles (mobile vs desktop) once push ships?

---

## Suggestions (to improve effectiveness)

- **Start small, measure**: Ship Phase 1 to a few workspaces; track complaint rate (mute, dismiss) vs action rate (click-through) per type.
- **Keyword UX copy**: Provide examples and show a live preview of matches.
- **Agent etiquette**: Add SDK helpers so agents emit only milestone updates; provide a `notifyOncePerThread()` utility.
- **Digest by default**: For agent streams, default to summarized digests with quick-expand.
- **One inbox**: Keep a unified notifications pane with filters; avoid multiple disjoint counters.

---

## Acceptance Criteria (MVP)

- P95 in-app latency ≤ 150 ms; durable inbox shows the last 30 days.
- Mentions/replies/tasks generate exactly one actionable notification per unseen thread.
- Global/workspace preferences, DND, and snooze work as expected.
- Unread badge stays consistent across tabs/devices via WS + sync fetch.

