April 20th 2025AD Sunday 9:46PM

God bless us all! 

I had one like this July/August 2024AD, I'll fetch it and add it onto here. It was mostly breaking down projects it could do by language/framework. 

This one is going to be towards end results that could be used by humans or penguins (and future agents) in everyday stuff. 

Like LinkAI, or other stuff.

## Example Penguin Test Projects

### 1. Team Tasks API
- **Type:** Python CRUD / backend service
- **Stack:** FastAPI, SQLite, pytest
- **Why it is useful:**
  - exercises authenticated CRUD flows
  - good fit for `project init --blueprint` and `project start`
  - realistic enough to test Bootstrap, RunMode, project/task orchestration, and later TUI/web flows
  - small enough to iterate quickly without becoming architecture theater
- **Suggested scope:**
  - auth/register/login
  - task CRUD
  - task filtering
  - audit trail for changes
  - tests and basic validation
- **Example blueprint:**
  - `misc/example_crud_blueprint.md`

### 2. Personal Notes API
- **Type:** Python CRUD / API + local persistence
- **Stack:** FastAPI or Flask, SQLite, pytest
- **Why it is useful:**
  - slightly simpler than a team-task system
  - good for basic project bootstrap and verification testing
  - exercises create/read/update/delete plus search/filtering
- **Suggested scope:**
  - notebook CRUD
  - note tagging
  - keyword search
  - basic auth or local-only mode

### 3. Inventory Tracker
- **Type:** Python CRUD / admin-style backend
- **Stack:** FastAPI, SQLite/Postgres, pytest
- **Why it is useful:**
  - tests more realistic business rules than pure toy CRUD
  - useful for validating project dependencies and acceptance criteria
- **Suggested scope:**
  - product CRUD
  - stock adjustments
  - transaction history
  - low-stock reporting

### 4. Simple Bookings Backend
- **Type:** Python service with CRUD + state transitions
- **Stack:** FastAPI, SQLite, pytest
- **Why it is useful:**
  - adds lifecycle/status transitions beyond plain CRUD
  - good for testing review/approval-ish workflows later
- **Suggested scope:**
  - create booking
  - confirm/cancel booking
  - list/filter bookings
  - basic conflict validation

## Recommendation
If we want one practical default project for testing Penguin right now, use:

- **Team Tasks API**

It is realistic, exercises a lot of the stack, and is still small enough to iterate on quickly.
