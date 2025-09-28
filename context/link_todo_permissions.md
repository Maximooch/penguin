## Link Permissions & Workspaces Plan (MVP → V1)

### Goals and principles
- **Unreasonably effective**: 3× capability at 1/3 complexity. A single unified backbone serves both "Link Work" and "Link Chat" with small domain toggles.
- **Discord-like mental model**: A "server" is a `workspace`. Channels, projects, and agents live inside a workspace. Roles and permission overwrites feel familiar.
- **Safety by default**: Explicit allow; denies override allows; least-privilege defaults; thorough auditability.
- **Composable**: Start with RBAC + resource-scoped overwrites, with a clean path to ABAC later.

---

## Core concepts
- **Workspace (aka Server)**: Top-level container for people, channels, projects, tasks, agents, and integrations.
- **Member**: A user inside a workspace; can hold multiple roles.
- **Role**: Named bundle of permissions using a bitset; ordered for display only (not evaluation).
- **Permission**: Atomic capability (bit). Grouped by domain; evaluated with allow/deny and resource-scoped overrides.
- **Resource**: Anything permissions can target. Key types: `workspace`, `channel`, `thread`, `project`, `task`, `doc`, `file`, `agent`, `integration`, `secret`, `webhook`.
- **Override**: Resource-level allow/deny for a role or a specific member, similar to Discord channel overrides.
- **Scope**: Where a grant applies: workspace-wide, or narrowed to a specific resource (e.g., a channel or project).
- **Agent/Bot**: Non-human actor with an ephemeral, scoped token minted by Link.

---

## Unified RBAC model (Link Work and Link Chat)

### Default roles
- **Owner**: Full access, cannot be removed except by self-transfer.
- **Admin**: Manage workspace, roles (except Owner), members, billing-optional.
- **Moderator**: Manage channels, content, invites, and member discipline; no billing/roles.
- **Member**: Standard access. Create threads, send messages, create personal tasks.
- **Guest**: Read-only unless explicitly allowed on specific channels/projects.
- **Agent/Bot**: No human admin powers; only the actions granted in token scope.
- **External Collaborator** (optional): Limited to specific projects/channels.
- **Observer (Read-Only)**: For audits/demos; can read and download if permitted.

### Permission taxonomy (bitset)
Suggested 64-bit baseline, expandable to 128 if needed (store as two `BIGINT`s). Grouped for clarity. Names are canonical; UI shows friendly labels.

Workspace Admin domain
- `WORKSPACE_VIEW`
- `WORKSPACE_MANAGE_SETTINGS`
- `WORKSPACE_MANAGE_ROLES`
- `WORKSPACE_MANAGE_MEMBERS`
- `WORKSPACE_VIEW_AUDIT_LOG`
- `WORKSPACE_MANAGE_BILLING`
- `WORKSPACE_MANAGE_SECRETS`

Membership & Invites
- `INVITE_CREATE`
- `INVITE_REVOKE`
- `MEMBER_KICK`
- `MEMBER_BAN`

Channels & Messaging (Chat domain)
- `CHANNEL_CREATE`
- `CHANNEL_MANAGE`
- `CHANNEL_DELETE`
- `MESSAGE_READ`
- `MESSAGE_SEND`
- `MESSAGE_THREAD_CREATE`
- `MESSAGE_MANAGE` (pin/delete others)
- `ATTACHMENT_UPLOAD`
- `ATTACHMENT_DOWNLOAD`

Projects & Tasks (Work domain)
- `PROJECT_CREATE`
- `PROJECT_MANAGE`
- `TASK_CREATE`
- `TASK_ASSIGN`
- `TASK_EDIT`
- `TASK_MOVE`
- `TASK_DELETE`
- `TASK_VIEW`

Docs & Files
- `DOC_CREATE`
- `DOC_EDIT`
- `DOC_DELETE`
- `DOC_VIEW`
- `FILE_MANAGE`

Agents & Integrations
- `AGENT_RUN`
- `AGENT_MANAGE`
- `INTEGRATION_MANAGE`
- `WEBHOOK_MANAGE`

Security & Governance
- `RATE_LIMIT_BYPASS`
- `EXPORT_DATA`

Notes
- Both domains share the same bitset; features toggle visibility per workspace type. E.g., a Chat-first workspace hides "Projects" UI but keeps the backbone compatible.

---

## Permission scope and inheritance
- **Hierarchy**: `workspace` → `channel | project` → `thread | task | doc`
- **Inheritance**: Permissions granted at workspace flow down unless explicitly denied at a child resource.
- **Overrides**: On any resource, set allow/deny per Role or Member. Deny always wins over allow.
- **Owner bypass**: Owner always passes checks (except hard-platform constraints like billing provider errors).

Evaluation order
1) Aggregate role grants at workspace scope
2) Apply workspace-level member-specific overrides (if any)
3) Walk down the resource chain, applying overrides at each level (role then member)
4) Compute final: `effective = (allow_bits & ~deny_bits)`; check `required ⊆ effective`

Pseudo-code
```python
def has_perm(member, action_bits, resource_path):
    allow = 0
    deny = 0
    # 1) Aggregate roles at workspace
    for role in member.roles:
        allow |= role.allow_bits
        deny  |= role.deny_bits

    # 2) Member overrides at workspace
    allow, deny = apply_overrides(allow, deny, member, resource_path.workspace)

    # 3) Descend resource chain (e.g., workspace → project → task)
    for res in resource_path.chain():
        allow, deny = apply_overrides(allow, deny, member, res)

    effective = allow & (~deny)
    return (effective & action_bits) == action_bits
```

Override application
```python
def apply_overrides(allow, deny, member, resource):
    # Role overrides on this resource
    for role in member.roles:
        o = get_override(resource, subject=('role', role.id))
        if o:
            allow |= o.allow_bits
            deny  |= o.deny_bits
    # Member-specific override
    o = get_override(resource, subject=('member', member.id))
    if o:
        allow |= o.allow_bits
        deny  |= o.deny_bits
    return allow, deny
```

---

## Link Work vs Link Chat
- **Shared backbone**: Same member/role/override engine, same evaluation.
- **Feature flags per workspace**:
  - Link Chat: show Channels/Messaging; hide Projects/Tasks by default.
  - Link Work: show Projects/Tasks/Docs; Channels optional.
- **Domain-specific defaults**:
  - Chat: `MESSAGE_READ`, `MESSAGE_SEND`, `THREAD_CREATE` enabled for `Member` by default; `Moderator` has `CHANNEL_MANAGE`, `MESSAGE_MANAGE`.
  - Work: `TASK_CREATE`, `TASK_EDIT`, `TASK_VIEW` enabled for `Member`; `Moderator` has `PROJECT_MANAGE` and `TASK_DELETE`.

---

## Backend data model (PostgreSQL)

Key tables
```sql
-- Users and Workspaces
CREATE TABLE users (
  id UUID PRIMARY KEY,
  email TEXT UNIQUE NOT NULL,
  name TEXT NOT NULL,
  avatar_url TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE workspaces (
  id UUID PRIMARY KEY,
  name TEXT NOT NULL,
  type TEXT NOT NULL CHECK (type IN ('chat','work','hybrid')),
  owner_id UUID NOT NULL REFERENCES users(id),
  settings JSONB DEFAULT '{}'::jsonb,
  acl_version BIGINT DEFAULT 1,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE workspace_members (
  id UUID PRIMARY KEY,
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  nickname TEXT,
  joined_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(workspace_id, user_id)
);

-- Roles and bindings
CREATE TABLE roles (
  id UUID PRIMARY KEY,
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  color TEXT,
  is_default BOOLEAN DEFAULT FALSE,
  position INT NOT NULL DEFAULT 0, -- for UI ordering only
  allow_bits BIGINT NOT NULL DEFAULT 0,
  deny_bits  BIGINT NOT NULL DEFAULT 0,
  UNIQUE(workspace_id, name)
);

CREATE TABLE role_bindings (
  id UUID PRIMARY KEY,
  workspace_member_id UUID NOT NULL REFERENCES workspace_members(id) ON DELETE CASCADE,
  role_id UUID NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
  UNIQUE(workspace_member_id, role_id)
);

-- Resource registry (optional but useful for uniform overrides)
CREATE TABLE resources (
  id UUID PRIMARY KEY,
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  type TEXT NOT NULL, -- 'channel','project','task','doc', etc.
  parent_id UUID, -- parent resource id for hierarchy
  name TEXT,
  created_by UUID REFERENCES users(id),
  created_at TIMESTAMPTZ DEFAULT now()
);

-- Permission overrides (role or member subjects) per resource
CREATE TABLE permission_overrides (
  id UUID PRIMARY KEY,
  resource_id UUID NOT NULL REFERENCES resources(id) ON DELETE CASCADE,
  subject_type TEXT NOT NULL CHECK (subject_type IN ('role','member')),
  subject_id UUID NOT NULL, -- role.id or workspace_members.id
  allow_bits BIGINT NOT NULL DEFAULT 0,
  deny_bits  BIGINT NOT NULL DEFAULT 0,
  UNIQUE(resource_id, subject_type, subject_id)
);

-- Invites and tokens
CREATE TABLE invites (
  id UUID PRIMARY KEY,
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  created_by UUID NOT NULL REFERENCES users(id),
  code TEXT UNIQUE NOT NULL,
  max_uses INT,
  expires_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE agent_tokens (
  id UUID PRIMARY KEY,
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  agent_id UUID, -- optional link to an agent registry
  issued_by UUID NOT NULL REFERENCES users(id),
  jti TEXT UNIQUE NOT NULL,
  scope JSONB NOT NULL, -- { allow_bits, deny_bits, resources: [ids], ttl }
  expires_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now(),
  revoked_at TIMESTAMPTZ
);

-- Audit log
CREATE TABLE audit_log (
  id BIGSERIAL PRIMARY KEY,
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  actor_type TEXT NOT NULL CHECK (actor_type IN ('user','agent')),
  actor_id TEXT NOT NULL,
  action TEXT NOT NULL,
  target_type TEXT,
  target_id TEXT,
  metadata JSONB,
  created_at TIMESTAMPTZ DEFAULT now()
);
```

Indexes and perf
- Add composite indexes: `permission_overrides(resource_id, subject_type, subject_id)` and `resources(workspace_id, type)`.
- Keep `acl_version` on `workspaces`; bump on any ACL change to invalidate caches.

---

## API surface (tRPC or REST)

Roles & Members
- `GET /workspaces/:id/roles`
- `POST /workspaces/:id/roles` (name, allow_bits, deny_bits)
- `PATCH /roles/:id` (rename, bits, position)
- `DELETE /roles/:id`
- `POST /workspaces/:id/members/:memberId/roles/:roleId`
- `DELETE /workspaces/:id/members/:memberId/roles/:roleId`

Overrides
- `GET /resources/:id/overrides`
- `PUT /resources/:id/overrides` (upsert list)

Permission check & introspection
- `POST /authz/check` → `{ allow: boolean, missing_bits: number }`
- `GET /authz/effective?member=...&resource=...` → computed bitset & explanation

Agents
- `POST /agents/tokens` → ephemeral token with `{ allow_bits, deny_bits, resource_ids, ttl }`
- `POST /agents/tokens/revoke` → by `jti`

Events (WebSocket)
- `acl:updated` (workspace scope)
- `resource:overrides_updated` (resource scope)

---

## Caching and runtime evaluation
- **Bitsets**: Fast in-memory checks. In DB store as `BIGINT` (or two for 128 bits). In app use `BigInt`.
- **Per-member cache**: Cache workspace base bitset (role union) keyed by `(workspace_member_id, acl_version)`.
- **Resource override cache**: Cache override rows by `resource_id`.
- **Invalidation**: Increment `acl_version` on any role/override change; publish `acl:updated`.

---

## UI/UX (Discord-like)

Workspace left sidebar
- Channels section (Chat) and Projects section (Work) are toggled by workspace type.
- Badges for unread, mentions, and agent activity.

Server Settings modal (gear next to workspace name)
- **Overview**: name, icon, workspace type toggle.
- **Roles**: list with draggable order; New Role button.
- **Role Editor**: color, name, and categorized permission toggles with search; bit usage indicator.
- **Members**: list with role pills; quick actions (promote, remove, ban, add role).
- **Invites**: create links with expiry and max uses.
- **Integrations**: manage webhooks, bots, OAuth installs.
- **Security**: secrets vault, token issuance policy.
- **Audit Log**: filterable table with actor, action, target, time.
- **Billing** (optional): plan, invoices.

Channel Settings drawer
- **Permissions**: matrix of Roles × Permissions with three states: Inherit, Allow, Deny.
- **Members** tab: add member-specific overrides.

Project Settings (Work)
- **Permissions**: same matrix pattern as channels.
- **Automation**: which agents may act on this project.

Member inspector (right-click on avatar/name)
- Quick role assignment, timeout/ban, view effective permissions.

Permission preview
- In-role-editor, a live preview explains what a toggle enables and shows example UI affordances that appear/disappear.

---

## Default role presets (suggested)

Owner
- All bits allowed. Hidden deny.

Admin
- Allow: `WORKSPACE_VIEW`, `WORKSPACE_MANAGE_SETTINGS`, `WORKSPACE_MANAGE_MEMBERS`, `WORKSPACE_MANAGE_ROLES`, `WORKSPACE_VIEW_AUDIT_LOG`, `INVITE_*`, `CHANNEL_*`, `PROJECT_*`, `TASK_*`, `DOC_*`, `AGENT_MANAGE`, `INTEGRATION_MANAGE`, `WEBHOOK_MANAGE`.
- Deny: `WORKSPACE_MANAGE_BILLING` (optional) and `WORKSPACE_MANAGE_SECRETS` unless explicitly trusted.

Moderator
- Allow: `MESSAGE_*` (except mass delete), `CHANNEL_MANAGE`, `INVITE_*`, `MEMBER_KICK`.
- Deny: `WORKSPACE_MANAGE_ROLES`, `WORKSPACE_MANAGE_SETTINGS`.

Member
- Allow: `MESSAGE_READ`, `MESSAGE_SEND`, `MESSAGE_THREAD_CREATE`, `ATTACHMENT_UPLOAD`, `TASK_VIEW`, `TASK_CREATE`, `TASK_EDIT` (own by policy), `DOC_VIEW`, `DOC_CREATE`.

Guest / Observer
- Allow: `MESSAGE_READ`, `TASK_VIEW`, `DOC_VIEW`.
- Everything else inherit/deny unless overridden per resource.

Agent/Bot (token-scoped)
- Allow: minimal, typically `AGENT_RUN`, and the specific resource-scoped bits needed (e.g., `TASK_EDIT` on project X). No workspace admin bits.

---

## Agents: scoped tokens
- Link mints short-lived JWTs for agents with:
  - `allow_bits` and `deny_bits`
  - `resource_ids` (whitelist) and `workspace_id`
  - `ttl`, `jti`, `issued_by`
- Backend middleware attaches an evaluator that treats agent tokens like a role union limited by the provided resource whitelist.
- Use-case examples: allow `TASK_EDIT` and `DOC_EDIT` on `project:abc` only; deny `DOC_DELETE` explicitly.

---

## Migration & seeding plan
1) Create tables above.
2) Seed default roles per workspace on creation.
3) Seed a default `#general` channel (Chat) or a default `Main Project` (Work) with sensible overrides.
4) Create first `workspace_member` as Owner.
5) Introduce `acl_version=1` and start emitting `acl:updated` on changes.

---

## Testing strategy
- Unit: bitset ops, allow/deny precedence, override application, owner bypass, agent token scoping.
- Property-based tests: random role/override graphs → check monotonicity of denies.
- Integration: create workspace → assign roles → set overrides → check endpoints.
- Snapshot tests: effective permissions explanations for common presets.

---

## Open questions / decisions to confirm
- Should `Admin` manage billing by default or keep it owner-only?
- Do we want per-message delete granularity (own vs others) split into separate bits now or later?
- For tasks: enforce "edit own only" via policy rule now, or add `TASK_EDIT_OWN` bit?
- Are voice/spaces planned for Chat? If yes, add `VOICE_CONNECT`, `VOICE_MUTE_MEMBERS`, etc.
- Secrets: keep a single workspace vault or per-project vault namespaces?
- External collaborators: require email domain allowlist or invite-only?
- Hard cap on number of roles per workspace (e.g., 250) for perf and UI sanity?

---

## Future-ready (post-MVP)
- ABAC conditions: time-based, IP allowlists, ownership constraints ("own task"), cost budgets.
- Teams/Groups: role assignment to teams; team membership for bulk changes.
- 128-bit expansion: second column `allow_bits_hi`/`deny_bits_hi`.
- Cross-workspace federation: guests from workspace A join resource in B via link contracts.
- Fine-grained doc permissions (section-level) if needed later.

---

## Milestones (1–3 weeks)
- Week 1: Tables, default roles, bitset constants, evaluator, basic UI for Roles and Members.
- Week 2: Resource overrides UI (channel + project), API for effective checks, audit log, invites.
- Week 3: Agent tokens + scoped evaluator, caching with `acl_version`, polish and tests.

