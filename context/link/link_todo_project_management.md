# Link Project Management System - Implementation Plan


<!-- NOTES (start: Feb 22 2026AD)

God bless us all!

Main thing I'm thinking about is how will I use this for Penguin and Link? 

I think the first thing is certainly tags/categories. There are things in scope or common sections of projects in Penguin and Link that don't justify their own project, but do need some degree of separation. 

Examples:

  Penguin:
    - prompting
    - api providers
    - tool system
    - event bus, anything related to the nervous system
    - web server

  Link:
    - front end
    - backend
    - project management
  
  Maybe some things related to either Penguin or Link that will probably diverge into different projects, typically because signifacant parts of it will be outside of the monorepo. 

  For example channel logic for inference engines. Or data wallets.

  Now you could have "sub-projects", or you can have "Products" defined and projects within those. But then there's the same thing roughly going on with teams in a company. That's just a question of inevitable scale. Task Groups?

  For now I think tasks that can cross to other tasks is needed because some work, like a Penguin/Link integration is integral for both projects.


 -->



> **Vision**: Build a world-class project management system that combines Linear's speed and elegance with AI-native collaboration. Make it the best PM tool for teams working with AI agents.

---

## 🎯 **The Opportunity**

Link has a unique advantage: **AI agents as first-class team members + Spec-driven development.**

Traditional PM tools (Linear, Jira, Asana) are designed for agile/sprint-based workflows with manual task tracking. Link will be fundamentally different:

### **Traditional Agile PM (Linear/Jira):**

- Issues/tasks are the atomic unit
- Bottom-up planning (tasks → sprints → epics)
- Iterative refinement through sprints
- Manual task breakdown by humans
- Progress tracking is the primary goal

### **Spec-Driven AI Development (Link):**

- **Specifications are the atomic unit**
- Top-down planning (spec → AI-generated tasks → execution)
- Waterfall-ish: spec → validate → generate → execute → review
- AI does the task breakdown automatically
- **Validation of AI work against spec is the primary goal**

Link will be the first PM system where:

- **Specifications drive all work** - not manually created tasks
- AI agents execute against validated specs
- Acceptance criteria are executable and trackable
- Real-time validation against domain models
- Agent work sessions are tightly coupled to specs

---

## 📊 **Current State Analysis**

### **✅ What Link HAS:**

**Database Schema:**

- `project` table (id, workspace_id, name, description, github_repo_url, status, created_by)
- `task` table (id, project_id, title, description, status, priority, assigned_to)
- `task_event` table (for activity tracking)
- `agent_work_session` table (tracks agent work on tasks with git branches)
- `task_branch` table (for task graph/DAG visualization)

**Backend API:**

- `projectRouter` - CRUD operations for projects
- `taskRouter` - Task management endpoints
- Relations between projects, tasks, agents

### **❌ What's MISSING:**

**UI - No frontend at all:**

- No project list view
- No project detail view
- No task board (Kanban/list)
- No task creation/editing
- No assignment UI
- No progress tracking views

**Schema Enhancements Needed:**

- Labels/tags for tasks
- Task dependencies (parent/child already in task_branch)
- Due dates
- Estimates and time tracking
- Task comments
- Custom fields
- Cycles/sprints
- Milestones

**Features:**

- No keyboard shortcuts
- No command palette for PM
- No bulk actions
- No filters/search within projects
- No task templates
- No project templates

### **📌 Implementation Decisions (2026-02-18)**

- Keep page channels **session-first** during current frontend refactor phases.
- Future PM surfaces should live under existing workspace-scoped routes (`/w/[workspaceId]/...`), not a parallel route tree.
- Project tab state should support deep-linking via URL query params.

---

## 🎨 **Design Inspiration: Linear**

### **What Makes Linear World-Class:**

#### **1. Speed & Performance**

- Instant loading (<100ms)
- Optimistic updates
- Keyboard-first design
- Near-instant search

#### **2. Keyboard Shortcuts**

- `C` - Create issue
- `Cmd+K` - Command palette
- `G then I` - Go to Inbox
- `G then V` - Go to current cycle
- `G then B` - Go to backlog
- `X` - Select item
- `Shift+Up/Down` - Multi-select
- `?` - Show all shortcuts

#### **3. Clean, Minimal UI**

- No clutter
- Fast view switching
- Contextual menus
- Multiple ways to do actions (mouse, keyboard, command palette)

#### **4. Smart Organization**

- Inbox (triage view)
- Cycles (sprints)
- Projects (initiatives)
- Teams (workspaces)
- Views (saved filters)

#### **5. Workflow Features**

- Status workflows (Backlog → Todo → In Progress → Done)
- Priority levels (No priority, Low, Medium, High, Urgent)
- Labels for categorization
- Assignee + due dates
- Estimates and time tracking
- Comments and activity log

---

## 🏗️ **Link PM Architecture**

### **Information Hierarchy:**

```
Workspace
├── Projects (initiatives/repos)
│   ├── Tasks (issues/work items)
│   │   ├── Subtasks
│   │   ├── Task Events (activity)
│   │   ├── Agent Work Sessions (AI work)
│   │   └── Task Branches (git branches)
│   ├── Milestones
│   ├── Cycles/Sprints
│   └── Project Channels (discussions)
├── Agents (team members)
└── Agent Sessions (work sessions)
```

### **Key Principles:**

**1. AI-Native Design**

- Agents are assignees just like humans
- Agent progress is real-time and visual
- AI work sessions linked to tasks
- Agent artifacts reviewed in-context

**2. Simplicity First**

- Start with core workflow (Linear-inspired)
- Add AI collaboration features
- Don't over-engineer

**3. Keyboard-Driven**

- Every action has a shortcut
- Command palette for everything
- Fast navigation

**4. Real-Time Everything**

- Live updates via WebSocket
- Optimistic UI updates
- Presence indicators

---

## 📐 **Enhanced Data Model**

### **Projects Table (Enhance Existing)**

```sql
-- Add to existing project table
ALTER TABLE project ADD COLUMN icon TEXT; -- Emoji or icon identifier
ALTER TABLE project ADD COLUMN color TEXT; -- Hex color for visual identity
ALTER TABLE project ADD COLUMN start_date DATE;
ALTER TABLE project ADD COLUMN target_date DATE;
ALTER TABLE project ADD COLUMN lead_id UUID REFERENCES account(id); -- Project lead
ALTER TABLE project ADD COLUMN settings JSONB DEFAULT '{}'::jsonb; -- Project-specific settings
ALTER TABLE project ADD COLUMN archived_at TIMESTAMPTZ;

-- Indices
CREATE INDEX idx_project_workspace_status ON project(workspace_id, status, archived_at);
CREATE INDEX idx_project_lead ON project(lead_id);
```

### **Tasks Table (Enhance Existing)**

```sql
-- Add to existing task table
ALTER TABLE task ADD COLUMN identifier TEXT; -- Human-readable ID like "LINK-123"
ALTER TABLE task ADD COLUMN parent_task_id UUID REFERENCES task(id); -- Subtasks
ALTER TABLE task ADD COLUMN estimate REAL; -- Story points or hours
ALTER TABLE task ADD COLUMN due_date DATE;
ALTER TABLE task ADD COLUMN started_at TIMESTAMPTZ;
ALTER TABLE task ADD COLUMN completed_at TIMESTAMPTZ;
ALTER TABLE task ADD COLUMN cycle_id UUID; -- Will reference cycles table
ALTER TABLE task ADD COLUMN milestone_id UUID; -- Will reference milestones table
ALTER TABLE task ADD COLUMN sort_order INTEGER DEFAULT 0; -- For manual ordering

-- Indices
CREATE INDEX idx_task_identifier ON task(project_id, identifier);
CREATE INDEX idx_task_assignee_status ON task(assigned_to, status);
CREATE INDEX idx_task_parent ON task(parent_task_id);
CREATE UNIQUE INDEX idx_task_project_identifier ON task(project_id, identifier);
```

### **New Tables:**

#### **Task Labels (Tagging System)**

```sql
CREATE TABLE task_label (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id UUID NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  color TEXT NOT NULL, -- Hex color
  description TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  UNIQUE(workspace_id, name)
);

CREATE TABLE task_label_assignment (
  task_id UUID NOT NULL REFERENCES task(id) ON DELETE CASCADE,
  label_id UUID NOT NULL REFERENCES task_label(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  PRIMARY KEY (task_id, label_id)
);

CREATE INDEX idx_task_label_assignment_label ON task_label_assignment(label_id);
```

#### **Task Comments**

```sql
CREATE TABLE task_comment (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  task_id UUID NOT NULL REFERENCES task(id) ON DELETE CASCADE,
  author_id UUID NOT NULL REFERENCES account(id) ON DELETE CASCADE,
  content TEXT NOT NULL,
  metadata JSONB DEFAULT '{}'::jsonb, -- mentions, attachments, etc.
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  edited_at TIMESTAMPTZ,
  is_deleted BOOLEAN DEFAULT FALSE
);

CREATE INDEX idx_task_comment_task ON task_comment(task_id, created_at DESC);
```

#### **Cycles/Sprints**

```sql
CREATE TABLE cycle (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id UUID NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
  name TEXT NOT NULL, -- "Sprint 23", "Q4 2025", etc.
  description TEXT,
  start_date DATE NOT NULL,
  end_date DATE NOT NULL,
  status TEXT NOT NULL DEFAULT 'planned', -- planned | active | completed
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  CONSTRAINT cycle_dates_check CHECK (end_date > start_date)
);

CREATE INDEX idx_cycle_workspace_status ON cycle(workspace_id, status, start_date);
```

#### **Milestones**

```sql
CREATE TABLE milestone (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID NOT NULL REFERENCES project(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  description TEXT,
  due_date DATE,
  status TEXT NOT NULL DEFAULT 'upcoming', -- upcoming | active | completed
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  completed_at TIMESTAMPTZ
);

CREATE INDEX idx_milestone_project ON milestone(project_id, status);
```

#### **Task Dependencies**

```sql
CREATE TABLE task_dependency (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  task_id UUID NOT NULL REFERENCES task(id) ON DELETE CASCADE,
  depends_on_task_id UUID NOT NULL REFERENCES task(id) ON DELETE CASCADE,
  dependency_type TEXT NOT NULL DEFAULT 'blocks', -- blocks | blocked_by | related_to
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  CONSTRAINT no_self_dependency CHECK (task_id != depends_on_task_id),
  UNIQUE(task_id, depends_on_task_id)
);

CREATE INDEX idx_task_dependency_task ON task_dependency(task_id);
CREATE INDEX idx_task_dependency_depends_on ON task_dependency(depends_on_task_id);
```

#### **Saved Views/Filters**

```sql
CREATE TABLE saved_view (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id UUID NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
  created_by UUID NOT NULL REFERENCES account(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  description TEXT,
  view_type TEXT NOT NULL, -- 'task_list' | 'kanban' | 'calendar' | 'table'
  filters JSONB NOT NULL, -- { status: ['todo', 'in_progress'], assignedTo: [...], etc. }
  sort_order JSONB, -- How to sort results
  is_shared BOOLEAN DEFAULT FALSE, -- Share with team
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_saved_view_workspace ON saved_view(workspace_id, is_shared);
CREATE INDEX idx_saved_view_creator ON saved_view(created_by);
```

---

## 🏗️ **Waterfall Workflow for Spec-Driven Development**

Link's PM system is organized around **stage gates** rather than sprints:

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│   DRAFT      │───→│   APPROVED   │───→│  PLANNING    │───→│ IN PROGRESS  │───→│  VALIDATING  │
│              │    │              │    │              │    │              │    │              │
│ Writing spec │    │ Spec review  │    │ AI generates │    │ Agent work   │    │ Test against │
│ & refinement │    │ & approval   │    │ tasks        │    │ sessions     │    │ acceptance   │
└──────────────┘    └──────────────┘    └──────────────┘    └──────────────┘    └──────────────┘
                                                                                         │
                                                                                         ↓
                                                              ┌──────────────┐    ┌──────────────┐
                                                              │  DEPLOYMENT  │←───│  COMPLETED   │
                                                              │              │    │              │
                                                              │ Ship to prod │    │ All criteria │
                                                              │              │    │ validated    │
                                                              └──────────────┘    └──────────────┘
```

### **Stage Gates:**

1. **Draft → Approved**: Human review of spec, requirements validation
2. **Approved → Planning**: AI task generation from spec (blocking gate)
3. **Planning → In Progress**: Task assignment to agents
4. **In Progress → Validating**: All generated tasks completed
5. **Validating → Completed**: All acceptance criteria pass
6. **Completed → Deployment**: Manual deployment decision

**Key Differences from Agile:**

- Can't skip stages (enforced stage gates)
- Changes to approved specs trigger re-validation
- No "sprints" - work flows through pipeline
- Validation is explicit and automated where possible

---

## 🎨 **The Four View System**

Instead of copying Linear's issue board, Link has **4 specialized views** for spec-driven development:

### **View 1: Spec Library** (Primary Planning View)

- **Purpose**: Browse, create, and manage specifications
- **Shows**: Tree/list of specs grouped by project, status, validation results
- **Actions**: Create spec, approve spec, view generated tasks
- **Primary users**: Product managers, tech leads, architects

**Analogies:**

- Like Notion's database view but for specs
- Like Confluence but executable
- Like GitHub Projects but spec-first

### **View 2: Task Graph** (Dependencies & Critical Path)

- **Purpose**: Visualize dependencies and identify bottlenecks
- **Shows**: Dependency graph with specs → tasks → agents
- **Actions**: Identify blockers, find parallel work, assign agents
- **Primary users**: Engineering managers, tech leads

**Analogies:**

- Like JIRA's dependency view
- Like MS Project's Gantt chart but as a graph
- Like GitHub's PR dependency graph

**Why it's critical for spec-driven development:**

```
Example: User Auth Spec has 15 generated tasks
- 3 can run in parallel (DB schema, API stubs, tests)
- 8 are blocked by schema completion
- 4 depend on API completion
- Graph shows critical path and parallelization opportunities
- Helps assign multiple agents efficiently
```

### **View 3: Execution Board** (Real-Time Work Tracking)

- **Purpose**: Monitor active work, not plan it
- **Shows**: Kanban/table of tasks currently in progress
- **Actions**: Check agent progress, review artifacts, monitor status
- **Primary users**: Everyone checking status

**Analogies:**

- Like Linear's issue board (but for monitoring, not planning)
- Like Trello but AI-aware
- Like GitHub Actions UI (showing running workflows)

**Filters:**

- By agent (what is Penguin working on?)
- By spec (how's the Auth Spec progressing?)
- By status (what's blocked?)

### **View 4: Validation Dashboard** (Quality Gate)

- **Purpose**: Validate completed work against specs
- **Shows**: Specs in validation phase with test results
- **Actions**: Review acceptance criteria, approve/reject, request changes
- **Primary users**: Tech leads, QA, stakeholders

**Analogies:**

- Like GitHub's PR review interface
- Like SonarQube's quality gate
- Like TestRail's test results dashboard

**Shows:**

```
┌─────────────────────────────────────────────────────┐
│ Spec: User Authentication System                    │
├─────────────────────────────────────────────────────┤
│ Acceptance Criteria: 12/15 ✓  (80% passing)        │
│ ✓ Passwords hashed with bcrypt                     │
│ ✓ JWT tokens expire after 15 minutes               │
│ ✗ Rate limiting: 5 attempts/15min (FAILING)        │
│ ✗ Email verification required (NOT IMPLEMENTED)    │
│ ⚠ Password reset tokens expire (TESTS MISSING)    │
│                                                      │
│ Test Coverage: 87% (target: 90%)                    │
│ Performance: ✓ All endpoints < 200ms               │
│                                                      │
│ [Request Changes] [Approve & Merge]                 │
└─────────────────────────────────────────────────────┘
```

---

## 🌐 **Open Source References & Inspiration**

Link draws inspiration from many existing tools. Here are key references:

### **Project Management:**

- **[Plane](https://github.com/makeplane/plane)** - Open source Linear alternative (similar UI/UX patterns)
- **[Leantime](https://github.com/Leantime/leantime)** - Open source PM with roadmaps and strategy focus
- **[Taiga](https://github.com/taigaio/taiga-back)** - Agile PM with Kanban/Scrum
- **[Focalboard](https://github.com/mattermost/focalboard)** - Notion-like boards by Mattermost

### **Specification & Documentation:**

- **[Gherkin/Cucumber](https://cucumber.io/docs/gherkin/)** - Spec format with executable acceptance criteria
- **[OpenAPI/Swagger](https://github.com/OAI/OpenAPI-Specification)** - API spec format that generates code/docs
- **[ADR Tools](https://github.com/npryce/adr-tools)** - Architecture Decision Records format
- **[RFC Process (IETF)](https://www.ietf.org/standards/rfcs/)** - Formal spec review process

### **Dependency & Graph Visualization:**

- **[ReactFlow](https://reactflow.dev/)** - React library for node-based UIs (primary choice)
- **[Dagre](https://github.com/dagrejs/dagre)** - Directed graph layout library
- **[Mermaid](https://mermaid.js.org/)** - Markdown-based diagramming (for specs)
- **[Cytoscape.js](https://js.cytoscape.org/)** - Graph theory visualization
- **[vis.js Network](https://visjs.github.io/vis-network/examples/)** - Network/graph visualization

### **Validation & Testing:**

- **[Allure Report](https://github.com/allure-framework/allure2)** - Test report framework
- **[SonarQube](https://github.com/SonarSource/sonarqube)** - Code quality gates
- **[Codecov](https://about.codecov.io/)** - Test coverage visualization
- **[TestRail](https://www.testrail.com/)** - Test case management (closed source reference)

### **AI-Native Development:**

- **[Cursor](https://cursor.sh/)** - AI-first code editor
- **[GitHub Copilot Workspace](https://githubnext.com/projects/copilot-workspace)** - AI-powered development environment
- **[Sweep](https://github.com/sweepai/sweep)** - AI junior developer that handles GitHub issues
- **[AutoGPT](https://github.com/Significant-Gravitas/AutoGPT)** - Autonomous AI agents

### **Command Palettes:**

- **[cmdk](https://github.com/pacocoursey/cmdk)** - React command palette (what we'll use)
- **[kbar](https://github.com/timc1/kbar)** - Alternative React command bar
- **[ninja-keys](https://github.com/ssleptsov/ninja-keys)** - Web component version

### **Design Systems:**

- **[Linear's Design System](https://linear.app/design)** - Our primary UX inspiration
- **[shadcn/ui](https://ui.shadcn.com/)** - React component library (what Link uses)
- **[Radix UI](https://www.radix-ui.com/)** - Unstyled accessible components

---

## 🧩 **Component Architecture**

### **Route Structure**

```
# New Spec-First Routes
/link/projects                          → Project list (all workspace projects)
/link/projects/[id]                     → Project detail with 4-view tabs
/link/projects/[id]/specs               → Spec Library View (primary)
/link/projects/[id]/specs/[specId]      → Spec detail/editor
/link/projects/[id]/graph               → Task Graph View
/link/projects/[id]/board               → Execution Board View (Kanban)
/link/projects/[id]/validation          → Validation Dashboard View
/link/projects/[id]/settings            → Project settings

# Legacy/Secondary Routes (still useful)
/link/tasks                             → All tasks (inbox view)
/link/tasks/[id]                        → Task detail (modal or side panel)
/link/cycles                            → Cycles overview (if using cycles)
/link/cycles/[id]                       → Cycle detail
```

### **Core Components**

#### **ProjectList.tsx**

- Grid of project cards
- Filters (status, lead, date range)
- Search projects
- Quick actions (archive, favorite)
- Create new project button

#### **ProjectDetail.tsx**

- Project header with metadata
- Tab navigation (Board, List, Table, Calendar, Activity, Settings)
- Task views (switchable)
- Project stats (progress, velocity, etc.)
- Team members panel

#### **TaskBoard.tsx** (Kanban)

- Columns by status (Backlog, Todo, In Progress, Review, Done)
- Drag-and-drop between columns
- Swimlanes (optional: by assignee, priority, label)
- Inline task creation
- Quick filters

#### **TaskList.tsx** (Linear-style list)

- Grouped by status
- Inline editing
- Bulk actions
- Keyboard shortcuts
- Virtual scrolling for performance

#### **TaskTable.tsx** (Spreadsheet view)

- Sortable columns
- Editable cells
- Custom columns
- Export to CSV
- Bulk edit mode

#### **TaskDetailPanel.tsx** (Side panel or modal)

- Task title (editable)
- Description (markdown)
- Status, priority, assignee dropdowns
- Labels
- Due date picker
- Estimate
- Comments thread
- Activity log
- Subtasks
- Dependencies
- Agent work sessions (if assigned to agent)
- Related artifacts

#### **CommandPalette.tsx** (Cmd+K)

```tsx
<CommandPalette>
  <CommandSection title="Actions">
    <Command>Create Task</Command>
    <Command>Create Project</Command>
    <Command>Assign to Me</Command>
  </CommandSection>

  <CommandSection title="Navigation">
    <Command>Go to Inbox</Command>
    <Command>Go to Active Tasks</Command>
    <Command>Go to Backlog</Command>
  </CommandSection>

  <CommandSection title="Search">
    <Command>Search Tasks...</Command>
    <Command>Search Projects...</Command>
  </CommandSection>
</CommandPalette>
```

---

## 📝 **Spec-Driven Development (Domain-Driven Design for AI)**

### **The Vision:**

Instead of manually creating individual tasks, teams write **specifications** that:

1. Define features/changes in structured markdown
2. Include acceptance criteria and domain models
3. Get parsed by AI into executable task breakdowns
4. Provide context for agent execution
5. Enable validation of completion

**This is Link's killer feature** - the bridge between product requirements and AI execution.

### **Spec System Architecture:**

#### **Project Spec Table:**

```sql
CREATE TABLE project_spec (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID NOT NULL REFERENCES project(id) ON DELETE CASCADE,
  version INTEGER NOT NULL DEFAULT 1,

  -- Spec content
  title TEXT NOT NULL,
  content TEXT NOT NULL, -- Markdown format
  spec_type TEXT NOT NULL DEFAULT 'feature', -- feature | bugfix | architecture | refactor | epic

  -- Metadata
  author_id UUID NOT NULL REFERENCES account(id),
  status TEXT NOT NULL DEFAULT 'draft', -- draft | review | approved | in_progress | implemented

  -- AI parsing results
  parsed_structure JSONB, -- Extracted requirements, domain models, etc.
  generated_task_ids UUID[], -- Tasks auto-created from this spec
  acceptance_criteria JSONB[], -- Structured acceptance criteria
  domain_model JSONB, -- Extracted entities, value objects, aggregates

  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  approved_at TIMESTAMPTZ,
  implemented_at TIMESTAMPTZ,

  UNIQUE(project_id, version)
);

CREATE INDEX idx_spec_project_status ON project_spec(project_id, status);
CREATE INDEX idx_spec_author ON project_spec(author_id);
```

#### **Spec Format (Markdown Template):**

```markdown
# Spec: User Authentication System

## Type

Feature

## Description

Build a complete user authentication system with JWT tokens, supporting registration, login, token refresh, and password reset flows.

## Requirements

- [ ] User registration with email/password
- [ ] Login with JWT token generation
- [ ] Token refresh mechanism
- [ ] Password reset via email
- [ ] Email verification
- [ ] Rate limiting on auth endpoints
- [ ] Secure password hashing (bcrypt)

## Acceptance Criteria

- [ ] All endpoints return proper HTTP status codes (200, 401, 403, 422, 500)
- [ ] Passwords are hashed with bcrypt (cost factor 12+)
- [ ] Access tokens expire after 15 minutes
- [ ] Refresh tokens expire after 30 days
- [ ] Rate limiting: max 5 login attempts per 15 minutes per IP
- [ ] All endpoints have integration tests with >90% coverage
- [ ] Email verification required before account activation
- [ ] Password reset tokens expire after 1 hour

## Domain Model

### Entities:

- **User**: id, email, password_hash, is_verified, created_at, updated_at
- **AuthToken**: id, user_id, token_hash, type (access|refresh), expires_at, revoked_at
- **PasswordReset**: id, user_id, token_hash, expires_at, used_at
- **LoginAttempt**: id, user_id, ip_address, success, attempted_at

### Value Objects:

- **Email**: Validated email address
- **Password**: Min 8 chars, requires uppercase, lowercase, number, symbol
- **JWTClaims**: user_id, email, issued_at, expires_at

### Aggregates:

- **UserAccount**: User + AuthTokens + LoginHistory

### Domain Events:

- UserRegistered (user_id, email, timestamp)
- UserVerified (user_id, timestamp)
- UserLoggedIn (user_id, ip_address, timestamp)
- TokenRefreshed (user_id, old_token_id, new_token_id)
- PasswordResetRequested (user_id, timestamp)
- PasswordChanged (user_id, timestamp)

## Technical Context

- Framework: FastAPI
- Database: PostgreSQL
- Cache: Redis (for token blacklist and rate limiting)
- Email: SendGrid or AWS SES
- Security: Follow OWASP Top 10 guidelines

## Dependencies

- Depends on: Database schema migrations (BACKEND-42)
- Blocks: User profile API (BACKEND-44), Social login (BACKEND-50)

## Estimated Effort

- Story points: 13
- Time estimate: 4-5 days
- Agent recommendation: Backend specialist agent

## Test Strategy

- Unit tests for domain logic
- Integration tests for API endpoints
- Security testing (SQL injection, XSS, CSRF)
- Load testing (1000 concurrent login requests)
```

### **Spec Workflow:**

```
1. WRITE SPEC
   │
   ├─> User writes spec in markdown
   ├─> Attach mockups, diagrams, references
   └─> Save as draft
   │
2. AI PARSING
   │
   ├─> Click "Generate Tasks" button
   ├─> Call Penguin SpecificationParser API
   ├─> AI extracts:
   │   ├─ Requirements list
   │   ├─ Acceptance criteria
   │   ├─ Domain model (entities, events, etc.)
   │   ├─ Task breakdown (phases → epics → tasks)
   │   ├─ Dependencies
   │   └─ Estimates
   │
3. REVIEW & REFINE
   │
   ├─> User sees proposed task tree
   ├─> Edit task titles/descriptions
   ├─> Reorder tasks
   ├─> Adjust estimates
   ├─> Modify acceptance criteria
   └─> Add/remove tasks
   │
4. APPROVE & CREATE
   │
   ├─> User approves spec
   ├─> Tasks created in PostgreSQL
   ├─> All linked to spec_id
   ├─> Acceptance criteria attached to tasks
   └─> Ready for assignment
   │
5. EXECUTION
   │
   ├─> Assign tasks to agents
   ├─> Agents receive spec context + acceptance criteria
   ├─> Agents execute with domain model awareness
   ├─> Agents validate against acceptance criteria
   └─> Agents report completion
   │
6. VALIDATION
   │
   ├─> All acceptance criteria checked?
   ├─> Tests passing?
   ├─> Spec status → "Implemented"
   └─> Project progresses
```

### **Integration with Task System:**

**Task Schema Enhancement:**

```sql
-- Add to task table
ALTER TABLE task ADD COLUMN spec_id UUID REFERENCES project_spec(id);
ALTER TABLE task ADD COLUMN acceptance_criteria JSONB; -- Criteria for THIS task
ALTER TABLE task ADD COLUMN domain_context JSONB; -- Relevant domain model info

CREATE INDEX idx_task_spec ON task(spec_id);
```

**Benefits:**

- **Traceability**: Task → Spec → Requirements
- **Context for AI**: Agents get full context from spec
- **Validation**: Auto-check completion against criteria
- **Living Documentation**: Spec stays linked to implementation

---

## 🚀 **UPDATED Implementation Roadmap**

### **Phase 1: Core Backend Foundation (Week 1-2)** ✅ **~85% COMPLETE**

**Week 1: Database Schema Enhancements**

**Day 1-2: Core PM Tables** ✅ **COMPLETE**

- [x] Enhance `project` table (icon, color, key, dates, lead, settings)
- [x] Enhance `task` table (identifier, parent, estimate, dates, cycle, milestone, spec_id, acceptance_criteria, domain_context)
- [x] Add `project_key` column to project (for BACKEND, WEB, etc.)
- [x] Add `identifier_sequence` to projects (auto-increment per project)
- [x] Add `task_assignee` junction table (for multiple assignees)
- [x] Update task status enum to include: backlog, todo, in_progress, review, done, cancelled
- [x] Create `task_label` and `task_label_assignment` tables
- [x] Create `task_comment` table
- [x] Run migrations (028_enhance_project_management_system.sql)

**Day 3: Advanced PM Tables** ✅ **COMPLETE**

- [x] Create `cycle` table
- [x] Create `milestone` table
- [x] Create `task_dependency` table
- [x] Create `saved_view` table
- [x] Add all necessary indices
- [x] Add full-text search indices (project name/description, task title/description)
- [x] Run migrations (029_add_rls_to_pm_tables.sql)

**Day 4-5: Backend API Core** ✅ **~70% COMPLETE**

- [x] Enhance `projectRouter`:
  - [x] Add project key generation
  - [x] Add stats endpoint (task counts by status)
  - [x] Add detailedStats endpoint (with agents, tasks breakdown)
  - [x] Add activity feed endpoint
- [x] Enhance `taskRouter`:
  - [x] Add identifier auto-generation (PROJECT-{number})
  - [x] Add assignees support (multiple assignees via task_assignee table)
  - [x] Add labels support
  - [x] Add subtask queries (parent_task_id)
  - [x] Add bulk update endpoint
  - [x] Enhanced task detail query (with assignees, labels, comments, dependencies, subtasks)
  - [x] Task event tracking (status changes, assignments)
- [ ] Create `labelRouter` for label management **← STILL NEEDED**
- [ ] Create `commentRouter` for task comments **← STILL NEEDED**
- [ ] Add full-text search endpoint for tasks/projects **← STILL NEEDED**

---

**Week 2: Advanced Backend & Spec System**

**Day 1-2: Spec System Backend**

- [ ] Create `project_spec` table with versioning
- [ ] Create `specRouter` with CRUD operations
- [ ] Add spec parsing endpoint (integrates with Penguin SpecificationParser)
- [ ] Add task generation endpoint (spec → tasks)
- [ ] Add acceptance criteria tracking
- [ ] Add domain model extraction

**Day 3: Cycles, Milestones, Dependencies**

- [ ] Create `cycleRouter` for cycle/sprint management
- [ ] Create `milestoneRouter` for milestone tracking
- [ ] Add dependency management endpoints
- [ ] Add circular dependency detection
- [ ] Add critical path calculation

**Day 4: Search & Performance**

- [ ] Add PostgreSQL full-text search indices
- [ ] Create unified search endpoint (tasks + projects + specs)
- [ ] Add search ranking algorithm
- [ ] Optimize queries for 10K+ tasks
- [ ] Add database query caching
- [ ] Test performance benchmarks

**Day 5: Views & Bulk Actions**

- [ ] Create `viewRouter` for saved views/filters
- [ ] Add bulk action endpoints:
  - [ ] Bulk status update
  - [ ] Bulk assignee change
  - [ ] Bulk label assignment
  - [ ] Bulk delete
- [ ] Add task templates endpoint
- [ ] Add view sharing/permissions

---

### **Phase 2: Core UI (Week 3-5)**

**Week 3: Projects & Navigation** ✅ **COMPLETE**

**Day 1-2: Project List & Creation** ✅ **COMPLETE**

- [x] Build `/link/projects` route
- [x] Build `ProjectList.tsx` with grid layout
- [x] Build `ProjectCard.tsx` component
- [x] Build `CreateProjectDialog.tsx`
  - [x] Name, description, key (auto-generated or custom)
  - [x] Icon picker (emoji)
  - [x] Color picker
  - [x] GitHub repo URL
  - [x] Project lead selector
- [x] Connect to backend API
- [x] Add loading states and empty states

**Day 3-4: Project Detail View** ✅ **COMPLETE**

- [x] Build `/link/projects/[id]` route
- [x] Build `ProjectDetail.tsx` layout
- [x] Build `ProjectHeader.tsx`:
  - [x] Breadcrumbs
  - [x] Project name (editable inline)
  - [x] Status badge
  - [x] Quick stats (tasks count, progress %)
  - [x] Actions menu (settings, archive, delete)
- [x] Tab navigation component (Overview, Board, List, Activity)
- [x] Project overview tab (stats, recent activity, team members)
- [x] Activity feed tab

**Day 5: Command Palette Foundation** ✅ **COMPLETE**

- [x] Install `cmdk` library
- [x] Build `CommandPalette.tsx` base
- [x] Add Cmd+K global shortcut
- [x] Add basic commands (Create Task, Create Project, Search)
- [x] Add recent items section
- [x] Add keyboard navigation

---

**Week 4: Task Board (Kanban)** ✅ **~80% COMPLETE**

**Day 1-2: Kanban Board Core** ✅ **COMPLETE**

- [x] Install `@dnd-kit/core` and `@dnd-kit/sortable`
- [x] Build `TaskBoard.tsx` layout with drag-and-drop
- [x] Build `BoardColumn.tsx` for each status
- [x] Build `TaskCard.tsx` for Kanban cards:
  - [x] Task identifier (clickable)
  - [x] Title
  - [x] Assignee avatar(s)
  - [x] Labels
  - [x] Priority indicator
  - [x] Due date (if set)
  - [x] Estimate
  - [x] Comment count
  - [x] Agent session indicator (if assigned to agent)

**Day 3: Drag-and-Drop** ✅ **COMPLETE**

- [x] Implement drag-and-drop between columns
- [x] Optimistic status updates
- [x] Drag preview component (DragOverlay with rotation effect)
- [x] Drop zone highlights
- [x] Reorder within column (SortableContext)
- [x] Handle errors gracefully (rollback on failure via mutation)

**Day 4: Inline Task Creation** ✅ **COMPLETE**

- [x] "Add task" button at bottom of each column
- [x] Inline input appears
- [x] Type and press Enter to create
- [x] Auto-assign to current column status
- [x] Focus management (autoFocus, Escape to cancel)

**Day 5: Board Filtering & Search** ← **NOT YET IMPLEMENTED**

- [ ] Filter bar component
- [ ] Filter by assignee
- [ ] Filter by label
- [ ] Filter by priority
- [ ] Search tasks in board
- [ ] Clear filters button

---

**Week 5: Task List & Detail** ✅ **~70% COMPLETE**

**Day 1-2: Task List View (Linear-style)** ✅ **COMPLETE**

- [x] Build `TaskList.tsx` with grouping
- [x] Group by status (collapsible sections with ChevronRight icon)
- [x] Status icons and colors (Circle, Clock, CheckCircle2, etc.)
- [x] Compact row design with all task metadata
- [x] Assignee avatars with overflow indicators
- [x] Priority badges with color coding
- [x] Labels display (first 2 + overflow count)
- [x] Estimate display
- [ ] Virtual scrolling for 1000+ tasks (not needed yet - renders fast) **← TODO**
- [ ] Keyboard navigation (↑↓, Enter, X for select) **← TODO**
- [ ] Multi-select with Shift+Click **← TODO**
- [ ] Inline editing **← TODO**

**Day 3-4: Task Detail Panel** ✅ **~80% COMPLETE**

- [x] Build `TaskDetailPanel.tsx` (Sheet slide-over from right)
- [x] Editable title with auto-save on blur
- [x] Description editor with click-to-edit and save/cancel
- [x] Status dropdown
- [x] Priority dropdown (with colored options)
- [x] Assignees display with AI agent sparkle indicator
- [x] Labels display with custom colors
- [x] Due date display
- [x] Estimate display
- [x] "Open in Agent Board" button (shown when hasAgentSession is true)
- [x] Comments section placeholder
- [x] Created/Updated metadata timestamps
- [ ] Parent task selector (for subtasks) **← TODO**
- [ ] Label selector with create option **← TODO**
- [ ] Due date picker (editable) **← TODO**
- [ ] Estimate input (editable) **← TODO**
- [ ] Assignee selector/editor **← TODO**

**Day 5: Task Creation** ← **NOT YET IMPLEMENTED**

- [ ] Quick create modal (Cmd+K → "Create Task")
- [ ] Full create form dialog
- [ ] Default status to "todo"
- [ ] Auto-generate identifier (PROJECT-{number})
- [ ] Create and open immediately

---

### **Phase 3: Spec System UI (Week 6)**

**Week 6: Spec-Driven Task Generation**

**Day 1-2: Spec Editor**

- [ ] Build `/link/projects/[id]/specs` route
- [ ] Build `SpecList.tsx` for project specs
- [ ] Build `SpecEditor.tsx`:
  - [ ] Markdown editor for spec content
  - [ ] Template selector (feature, bugfix, architecture, etc.)
  - [ ] Live preview
  - [ ] Auto-save drafts
- [ ] Build `SpecHeader.tsx` with status and actions

**Day 3: AI Task Generation**

- [ ] Build `TaskGenerationPreview.tsx` component
- [ ] "Generate Tasks" button
- [ ] Call Penguin SpecificationParser via backend
- [ ] Show AI-proposed task tree
- [ ] Allow editing before creation
- [ ] Show extracted acceptance criteria
- [ ] Show extracted domain model

**Day 4: Spec Review & Approval**

- [ ] Spec approval workflow UI
- [ ] Version comparison (when spec changes)
- [ ] Re-generate tasks from updated spec
- [ ] Track which tasks are linked to spec
- [ ] Spec status indicators

**Day 5: Acceptance Criteria Tracking**

- [ ] Display acceptance criteria in task detail
- [ ] Checkbox UI for marking criteria complete
- [ ] Auto-update spec progress when tasks complete
- [ ] Visual progress bar for spec completion
- [ ] Domain model viewer (entity diagrams)

---

### **Phase 4: Advanced Features (Week 7-8)**

**Week 7: Comments, Dependencies, Polish**

**Day 1-2: Task Comments**

- [ ] Build `TaskComments.tsx` thread
- [ ] Comment composer with markdown
- [ ] @mention support (users and agents)
- [ ] Real-time comment updates
- [ ] Edit/delete own comments
- [ ] Emoji reactions

**Day 3: Dependencies & Subtasks**

- [ ] Build `DependencyGraph.tsx` visualization
- [ ] Dependency picker UI
- [ ] Block indicators on tasks
- [ ] Subtask list in task detail
- [ ] Create subtask inline
- [ ] Subtask progress rollup to parent

**Day 4-5: Cycles & Milestones**

- [ ] Build `CycleList.tsx` view
- [ ] Cycle creation dialog
- [ ] Assign tasks to cycles
- [ ] Build `MilestoneList.tsx`
- [ ] Milestone progress view
- [ ] Burndown chart (simple version)

---

**Week 8: Labels, Saved Views, Polish**

**Day 1-2: Labels & Filtering**

- [ ] Build `LabelManager.tsx` in workspace settings
- [ ] Label picker component
- [ ] Color picker for labels
- [ ] Filter UI in all views
- [ ] Combine multiple filters

**Day 3: Saved Views**

- [ ] Build `SavedViewManager.tsx`
- [ ] Save current filter/sort as view
- [ ] View switcher dropdown
- [ ] Share views with team
- [ ] View templates (My Tasks, Team Tasks, Blocked, etc.)

**Day 4-5: Final Polish**

- [ ] Keyboard shortcuts overlay (? key)
- [ ] Loading skeletons everywhere
- [ ] Error boundaries
- [ ] Empty states with helpful CTAs
- [ ] Optimistic updates for all actions
- [ ] Performance audit
- [ ] Accessibility audit
- [ ] E2E tests for critical flows

---

## 💭 **Additional Thoughts & Recommendations**

### **1. GitHub Integration is Critical**

Since Penguin works with code and Link tracks projects:

- **Bi-directional sync** with GitHub issues/PRs
- **Branch → Task linking** (already have agent_work_session)
- **PR → Task status auto-update**
- **Commit messages** reference tasks (BACKEND-123)
- **CI/CD status** shown in task detail

This makes Link the command center for both AI and human development work.

### **2. Task Identifier Generation Strategy**

For `BACKEND-123` format:

```typescript
// Project key generation
function generateProjectKey(name: string): string {
  // "Link Backend" → "BACKEND"
  // "Web App" → "WEB"
  // "API Gateway" → "API"
  return name
    .split(' ')
    .map(word => word.toUpperCase())
    .filter(word => !['THE', 'A', 'AN'].includes(word))
    .slice(0, 2)
    .join('')
    .slice(0, 10);
}

// Task identifier
// Store counter in project table or separate sequence table
project: { key: "BACKEND", identifierSequence: 123 }
task: { identifier: "BACKEND-123" }
```

### **3. Multiple Assignees - Smart Default**

```typescript
// Project settings determine mode
project.settings = {
  assigneeMode: "single" | "multiple",
  requireAssignee: boolean,
  allowAgentAssignment: boolean,
  allowHumanAssignment: boolean,
};

// Default: single human OR single agent
// Advanced: multiple humans, multiple agents, or mixed teams
```

### **4. Spec Templates Library**

Provide built-in templates:

- **Feature Spec Template** (like my example)
- **Bug Fix Spec Template** (simpler)
- **Architecture Decision Record** (ADR format)
- **Refactoring Spec** (what to change, why, acceptance criteria)
- **API Design Spec** (RESTful conventions, endpoints, schemas)
- **Database Migration Spec** (schema changes, rollback plan)

Users can also create custom templates.

### **5. Real-Time Collaboration on Specs**

Like Google Docs:

- Live cursors showing who's editing
- Character-by-character sync
- Conflict resolution
- Version history with diffs
- Comments on specific sections

This makes spec writing collaborative between product/eng teams.

### **6. Acceptance Criteria as Tests**

```markdown
## Acceptance Criteria

- [ ] `GET /api/auth/login` returns 200 with valid credentials
- [ ] `GET /api/auth/login` returns 401 with invalid credentials
- [ ] Passwords stored with bcrypt hash
```

AI agents can:

- Generate test cases from these
- Auto-check criteria as tests pass
- Report which criteria are met/unmet

### **7. Domain Model Visualization**

Parse domain model from spec → Generate:

- Entity relationship diagrams
- Class diagrams
- Database schema suggestions
- TypeScript interfaces
- API endpoint stubs

Makes specs executable and visual.

### **8. Critical Path & Time Estimates**

With dependency graph + estimates:

- Calculate critical path
- Show "fastest possible completion"
- Highlight blocking tasks
- Suggest parallelization opportunities
- Estimate project completion date

### **9. Agent-Specific Considerations**

**Agent Task Cards Need:**

- Stream health indicator (is agent stuck?)
- Token usage counter (how much spent so far)
- Retry count (how many attempts?)
- Checkpoint/resume button
- "View Session" quick link
- Real-time progress bar

**Agent Assignment UI:**

- Show agent capabilities vs task requirements
- Recommend best agent for task
- Show agent current load
- Estimate cost/time
- One-click assign with auto-session creation

---

## 📝 **Spec System - Additional Details**

### **Spec Parser Endpoint:**

```typescript
// Backend endpoint to call Penguin
specRouter.parseSpec = protectedProcedure
  .input(
    z.object({
      specId: z.string().uuid(),
    }),
  )
  .mutation(async ({ ctx, input }) => {
    const spec = await getSpec(input.specId);

    // Call Penguin SpecificationParser
    const response = await fetch(`${PENGUIN_URL}/api/v1/specs/parse`, {
      method: "POST",
      body: JSON.stringify({
        content: spec.content,
        project_context: {
          name: spec.project.name,
          github_url: spec.project.githubRepoUrl,
        },
      }),
    });

    const parsed = await response.json();

    // Save parsed results
    await updateSpec(spec.id, {
      parsed_structure: parsed.structure,
      acceptance_criteria: parsed.acceptance_criteria,
      domain_model: parsed.domain_model,
      estimated_tasks: parsed.tasks,
    });

    return parsed;
  });
```

### **Spec Markdown Parsing Rules:**

Penguin should recognize these sections:

- `## Description` → Project description
- `## Requirements` → Checkbox list becomes tasks
- `## Acceptance Criteria` → Validation rules
- `## Domain Model` → DDD entities/events
- `## Technical Context` → Implementation constraints
- `## Dependencies` → Task relationships
- `## Estimated Effort` → Time/complexity

---

## 🎯 **Revised Priority Order**

### **Phase 1: Core Backend (Week 1-2)** ← START HERE

Focus on solid foundation for PM system

### **Phase 2: Core UI (Week 3-5)** ← THEN THIS

Kanban + List views, task detail, project views

### **Phase 3: Spec System (Week 6)** ← AFTER CORE WORKS

Add AI task generation on top of working PM

### **Phase 4: Advanced Features (Week 7-8)** ← POLISH

Comments, dependencies, cycles, etc.

---

## ❓ **Questions for You:**

**Q1: Project Keys**
Should project keys be:

- A) Auto-generated from name (BACKEND, WEB, API)
- B) User-defined during creation
- C) Auto-generated but editable

**Q2: Task Numbering**

- A) Global per project (BACKEND-1, BACKEND-2, ...)
- B) Per-status column (BACKEND-TODO-1, BACKEND-DONE-1)
- C) Just timestamps/UUIDs (no human-readable IDs)

**Q3: Spec System Timing**
Given we need specs for Penguin integration:

- A) Build spec system in Week 2 (parallel with backend)
- B) Build spec system in Week 6 (after core UI)
- C) Build minimal spec system early, enhance later

**Q4: GitHub Integration Priority**

- A) Essential for MVP (build in Phase 1-2)
- B) Nice-to-have (build in Phase 4)
- C) Post-MVP (focus on core PM first)

**Q5: Should we use Linear's exact status names?**

- A) Yes: Backlog, Todo, In Progress, In Review, Done (familiar)
- B) No: Customize for AI (e.g., "Agent Review" vs "In Review")
- C) Configurable per project

---

_Ready to start implementing once you confirm these decisions!_

- [ ] Create `task_dependency` table
- [ ] Create `saved_view` table
- [ ] Add all necessary indices
- [ ] Run migrations

**Day 3-4: Backend API Enhancements**

- [ ] Enhance `projectRouter` with new fields and queries
- [ ] Enhance `taskRouter` with advanced querying
- [ ] Create `cycleRouter` for cycle management
- [ ] Create `milestoneRouter` for milestone tracking
- [ ] Create `labelRouter` for label management
- [ ] Create `viewRouter` for saved views
- [ ] Add task dependency endpoints
- [ ] Add comment endpoints
- [ ] Add bulk action endpoints (bulk update status, assignee, etc.)

**Day 5: Search & Performance**

- [ ] Add full-text search indices for tasks/projects
- [ ] Create search endpoint with ranking
- [ ] Optimize queries for large datasets
- [ ] Add pagination cursors
- [ ] Test with 10,000+ tasks

---

### **Phase 2: Core UI (Week 3-4)**

**Week 3: Project & Task Views**

**Day 1-2: Project List & Detail**

- [x] Build `ProjectList.tsx` with grid/list toggle _(grid shipped; list toggle scheduled with filters work)_
- [x] Build `ProjectCard.tsx` component
- [x] Build `ProjectDetail.tsx` with tab navigation
- [x] Build `ProjectHeader.tsx` with breadcrumbs
- [x] Add project creation dialog
- [ ] Add project settings modal
- [x] Connect to backend API

**Day 3-4: Task Board (Kanban)**

- [ ] Build `TaskBoard.tsx` with drag-and-drop
- [ ] Install `@dnd-kit/core` for drag-and-drop
- [ ] Build `TaskCard.tsx` for Kanban cards
- [ ] Build `BoardColumn.tsx` for status columns
- [ ] Implement drag-to-status-change
- [ ] Add inline task creation
- [ ] Optimistic updates for drag actions

**Day 5: Task List View**

- [ ] Build `TaskList.tsx` (Linear-style)
- [ ] Grouped by status
- [ ] Inline editing for title, assignee, status, priority
- [ ] Keyboard navigation (↑↓ to navigate, Enter to open, X to select)
- [ ] Virtual scrolling with `react-virtual`
- [ ] Multi-select with bulk actions

---

**Week 4: Task Detail & Creation**

**Day 1-2: Task Detail Panel**

- [ ] Build `TaskDetailPanel.tsx` (slide-over or modal)
- [ ] Editable title with auto-save
- [ ] Markdown description editor
- [ ] Status/Priority/Assignee dropdowns
- [ ] Label selector with create option
- [ ] Due date picker
- [ ] Estimate input
- [ ] Parent task selector (for subtasks)
- [ ] Dependencies UI
- [ ] Link to Agent Session button (if assigned to agent)

**Day 3: Task Comments & Activity**

- [ ] Build `TaskComments.tsx` thread
- [ ] Comment composer with markdown
- [ ] Mention support (@user, @agent)
- [ ] Build `TaskActivity.tsx` log
- [ ] Activity feed showing all events (created, status changed, assigned, etc.)

**Day 4: Task Creation**

- [ ] Quick create modal (Cmd+K → "Create Task")
- [ ] Full create form with all fields
- [ ] Templates support (save common task types)
- [ ] Bulk create from markdown list

**Day 5: Subtasks & Dependencies**

- [ ] Subtask list in task detail
- [ ] Create subtask inline
- [ ] Dependency graph visualization
- [ ] Dependency picker UI
- [ ] Circular dependency detection

---

### **Phase 3: Advanced Features (Week 5-6)**

**Week 5: Cycles, Labels, Search**

**Day 1-2: Cycles/Sprints**

- [ ] Build `CycleList.tsx` view
- [ ] Build `CycleDetail.tsx` with progress charts
- [ ] Cycle creation dialog
- [ ] Assign tasks to cycles
- [ ] Cycle velocity metrics
- [ ] Burndown chart

**Day 2-3: Labels & Filtering**

- [ ] Build `LabelManager.tsx` for workspace labels
- [ ] Label picker component
- [ ] Filter UI in task views
- [ ] Multiple filters combination (AND/OR logic)
- [ ] Saved views with custom filters
- [ ] View templates

**Day 4: Search & Command Palette**

- [ ] Build `CommandPalette.tsx` (Cmd+K)
- [ ] Global search for tasks/projects
- [ ] Quick actions in palette
- [ ] Navigation commands
- [ ] Fuzzy matching
- [ ] Recent items history

**Day 5: Bulk Actions & Shortcuts**

- [ ] Multi-select UI (checkbox mode)
- [ ] Bulk actions menu (status, assignee, labels, delete)
- [ ] Keyboard shortcuts system
- [ ] Shortcuts overlay (? key)
- [ ] Custom keyboard bindings

---

**Week 6: Milestones, Views, Polish**

**Day 1: Milestones**

- [ ] Build `MilestoneList.tsx`
- [ ] Milestone creation/editing
- [ ] Link tasks to milestones
- [ ] Milestone progress view
- [ ] Milestone calendar

**Day 2: Advanced Views**

- [ ] Build `TaskTable.tsx` (spreadsheet view)
- [ ] Build `TaskCalendar.tsx` (calendar view)
- [ ] View switcher component
- [ ] Saved view management
- [ ] Share views with team

**Day 3-4: Polish & Performance**

- [ ] Loading skeletons for all views
- [ ] Error states
- [ ] Empty states with helpful CTAs
- [ ] Optimistic updates everywhere
- [ ] Performance testing with 10K+ tasks
- [ ] Virtualization for long lists

**Day 5: AI Integration Prep**

- [ ] "Assign to Agent" flow
- [ ] Agent work session display in task detail
- [ ] Link to Agent Board from task
- [ ] Agent progress indicators
- [ ] Agent artifact links

---

## 🤖 **AI-Native Features (Link's Differentiator)**

### **1. Agent Assignment**

**Workflow:**

```
User creates task → Assigns to Agent → Agent Session created automatically →
Agent works on task → Creates artifacts → User reviews → Approves → Task completed
```

**UI Enhancements:**

- Agent selector shows agent capabilities
- Real-time agent status indicator
- "View Agent Session" button in task detail
- Agent progress bar (based on session progress)
- Artifacts count in task card

### **2. Task-Session Linking**

**Bidirectional Navigation:**

- From Task → "Open in Agent Board" button → Opens agent session
- From Agent Session → Shows linked task in header
- Task status auto-updates based on session status
- Agent artifacts appear in task activity log

### **3. AI-Assisted Project Planning**

**Future:**

- "Generate project plan from description" button
- AI creates tasks from project spec
- AI suggests task breakdown
- AI estimates task complexity
- AI recommends agent for task

---

## 🎨 **Design System Patterns**

### **Colors & Status**

```typescript
// Task Status Colors (Linear-inspired)
const statusColors = {
  backlog: "text-gray-500 bg-gray-500/10",
  todo: "text-purple-500 bg-purple-500/10",
  in_progress: "text-blue-500 bg-blue-500/10",
  review: "text-yellow-500 bg-yellow-500/10",
  done: "text-green-500 bg-green-500/10",
};

// Priority Colors
const priorityColors = {
  urgent: "text-red-500 bg-red-500/10 border-red-500/20",
  high: "text-orange-500 bg-orange-500/10 border-orange-500/20",
  medium: "text-yellow-500 bg-yellow-500/10 border-yellow-500/20",
  low: "text-gray-500 bg-gray-500/10 border-gray-500/20",
};
```

### **Keyboard Shortcuts**

```typescript
// Global shortcuts (work anywhere)
'Cmd+K': 'Open command palette',
'C': 'Create task',
'P': 'Create project',
'/': 'Filter current view',
'?': 'Show keyboard shortcuts',

// Navigation
'G then I': 'Go to inbox (my tasks)',
'G then P': 'Go to projects',
'G then A': 'Go to all tasks',
'G then B': 'Go to backlog',

// Task actions (when task selected)
'Enter': 'Open task detail',
'E': 'Edit task',
'X': 'Select/deselect task',
'Shift+Up/Down': 'Multi-select',
'Delete': 'Delete selected tasks',

// In task detail
'Cmd+Enter': 'Save and close',
'Esc': 'Close without saving',
'A': 'Assign task',
'L': 'Add label',
'M': 'Set milestone',
```

---

## 🔗 **Integration with Penguin**

### **Link as Source of Truth**

**Architecture:**

```
┌─────────────────────────────────────────┐
│           Link (PostgreSQL)             │
│  - Projects                             │
│  - Tasks (source of truth)              │
│  - Agent Sessions                       │
│  - Artifacts                            │
└─────────────┬───────────────────────────┘
              │
              │ HTTP/WebSocket
              │
┌─────────────▼───────────────────────────┐
│         Penguin Instance                │
│  - Receives task from Link              │
│  - Executes with local SQLite context   │
│  - Streams progress back to Link        │
│  - Returns artifacts                    │
└─────────────────────────────────────────┘
```

**Flow:**

1. User creates task in Link → Saved to PostgreSQL
2. User assigns task to Penguin agent
3. Link calls Penguin API: `POST /api/v1/tasks/execute` with task details
4. Penguin creates local SQLite entry for execution context
5. Penguin works on task, streaming progress via WebSocket
6. Link receives progress updates → Updates task status in PostgreSQL
7. Penguin returns artifacts → Link creates `session_artifact` records
8. User reviews artifacts in Link → Approves/rejects
9. Task marked complete in Link PostgreSQL

**Penguin doesn't need to know about Link's schema** - it just:

- Receives task description/context via API
- Executes work
- Reports back progress and results
- Link handles all persistence and UI

---

## 📊 **Success Metrics**

### **Performance Targets** (Linear-level)

- Project list load: < 100ms
- Task board load: < 200ms
- Search results: < 150ms
- Drag-and-drop: 60fps
- Command palette open: < 50ms

### **User Experience**

- Time to create first task: < 10 seconds
- Time to find any task via search: < 3 seconds
- Keyboard shortcuts adoption: > 50% of users
- Task completion rate: > 80%

---

## 🎯 **Implementation Priority**

### **MVP (Must-Have) - 2-3 weeks:**

1. Enhanced database schema ✅
2. Backend API enhancements ✅
3. Project list & detail views
4. Task board (Kanban)
5. Task list view
6. Task detail panel
7. Basic search
8. Command palette (Cmd+K)

### **V1 (Should-Have) - +1-2 weeks:**

1. Labels and filtering
2. Cycles/sprints
3. Milestones
4. Comments
5. Saved views
6. Advanced search
7. Bulk actions

### **V2 (Nice-to-Have) - Post-launch:**

1. Table view
2. Calendar view
3. Dependencies visualization
4. Time tracking
5. Custom fields
6. Automations
7. API webhooks

---

## 💡 **Suggestions & Questions**

### **Suggestions:**

**1. Start Minimal, Iterate Fast**

- Launch with Kanban + List views only
- Add Table/Calendar later based on usage
- Get to usable fast, polish later

**2. Keyboard-First from Day 1**

- Build command palette first
- Add shortcuts as you build features
- Document shortcuts inline

**3. Steal Linear's Best Ideas Shamelessly**

- Linear's UX is proven
- Use their keyboard shortcuts (users know them)
- Match their speed and responsiveness

**4. But Add AI-Native Features**

- Agent assignment is your differentiator
- Make agent work highly visible
- Seamless task → agent session flow

**5. Consider Using Linear's API Structure**

- Similar endpoint patterns
- Compatible keyboard shortcuts
- Easier for Linear users to switch

### **Design Decisions** ✅ CONFIRMED:

**Q1: View Priority** → **A) Kanban + List first**

- Build Kanban and List views in Phase 2
- Add Table/Calendar in Phase 3 if needed

**Q2: Identifier Format** → **C) Project-based: `BACKEND-123`, `WEB-456`**

- Format: `{PROJECT_KEY}-{NUMBER}`
- More scalable than workspace-wide numbers
- Better for multi-project workspaces

**Q3: Status Workflow** → **B) Linear-style with 5 states**

- `Backlog` → `Todo` → `In Progress` → `Review` → `Done`
- Clean, proven workflow
- Review state important for AI work validation

**Q4: Assignee Model** → **B) Multiple assignees** (config-dependent)

- Support both single and multiple via project settings
- Default to single assignee
- Allow multiple for collaborative tasks

**Q5: Penguin Integration Timing** → **A) Build PM UI first, work on Penguin updates in parallel**

- Focus on PM foundation
- Penguin updates happen separately
- Integrate when both ready

---

## 🔮 **Future Vision: Beyond MVP**

### **AI-Powered Features:**

- Auto-triage inbox using AI
- AI suggests task priority based on context
- AI generates task descriptions from screenshots
- AI estimates task complexity
- AI recommends best agent for task
- AI creates subtasks automatically
- Natural language task creation ("Create a task to fix the login bug")

### **Advanced Collaboration:**

- Real-time collaborative editing (like Figma)
- Live cursors on task board
- Inline comments on task fields
- @mentions trigger notifications
- Task templates with AI pre-fill

### **Analytics & Reporting:**

- Velocity tracking per team/agent
- Burndown/burnup charts
- Cycle health metrics
- Agent productivity analytics
- Cost tracking (agent resource usage)

---

## 📋 **Future Considerations / Backlog**

### **Thread UI & Navigation**

- [ ] Build threads list/viewer UI to display task discussion threads
- [ ] Thread navigation from task detail panel
- [ ] Thread composer with markdown support
- [ ] Real-time updates for thread messages
- [ ] Thread-to-task linking in sidebar
- **Note**: Thread creation backend is implemented and working. Threads are being created in the database but are currently invisible due to missing UI.

### **Task Dependencies Visualization**

- [ ] Dependency graph component (similar to Linear's dependency viewer)
- [ ] Block indicators on task cards
- [ ] Dependency picker UI in task detail
- [ ] Circular dependency detection warnings
- [ ] Critical path highlighting

### **Enhanced Command Palette**

- [ ] Search for specific tasks by identifier or title
- [ ] Search for channels and navigate to them
- [ ] Recent items section (last viewed tasks/projects)
- [ ] Quick actions (assign to me, change status, etc.)
- [ ] Fuzzy search improvements

### **Keyboard Shortcuts**

- [ ] Global shortcuts system (C for create, G+P for projects, etc.)
- [ ] Shortcuts overlay (? key to show all)
- [ ] Multi-select with Shift+Click
- [ ] Navigation shortcuts (↑↓ in lists, J/K vim-style)
- [ ] Quick actions (X to select, E to edit, etc.)

### **Agent Work Sessions UI**

- [ ] Link agent sessions to tasks in UI
- [ ] "Open in Agent Board" button functionality
- [ ] Agent work progress indicators
- [ ] Agent session timeline/history
- [ ] Branch/PR integration from agent work

### **Task Branches/Graph View**

- [ ] Visual graph of task relationships
- [ ] Parent-child hierarchy visualization
- [ ] Dependency graph with direction indicators
- [ ] Expandable/collapsible nodes
- [ ] Pan and zoom controls

### **Comments System (Alternative to Threads)**

- [ ] Inline task comments (if threads UI not preferred)
- [ ] @mention support for users and agents
- [ ] Comment reactions/emoji
- [ ] Edit/delete permissions
- [ ] Comment notifications

---

_This project management system will make Link the most powerful platform for AI-assisted software development. Linear's speed + AI agent collaboration = unbeatable workflow._
