# Browser Domain Skills

Domain skills are opt-in host-specific playbooks for browser automation.

## Directory Shape

```text
domain-skills/
  example-com/
    scraping.md
    checkout.md
```

Use normalized hostname-ish directory names: lowercase, no scheme, replace dots with hyphens unless a clearer product name already exists.

## What Belongs Here

Capture durable public mechanics:

- stable URL patterns
- stable selectors or roles
- private-but-non-secret API shapes observed from the app
- page state transitions and waits
- SPA/network completion signals
- known iframe/shadow DOM/dropdown quirks
- safe test-user setup notes

Do not capture task narration, one-off coordinates, brittle pixel positions, or anything that only worked once.

## Redaction Workflow

Before saving a domain skill, run this mental diff:

1. **Could this identify the user or their organization?** If yes, remove or replace with `<org>`, `<account>`, `<workspace>`, `<project>`, or `<user>`.
2. **Could this authenticate or authorize a request?** Remove cookies, bearer tokens, API keys, CSRF tokens, signed URLs, session IDs, JWTs, OAuth codes, and magic links.
3. **Could this expose private data?** Remove emails, phone numbers, addresses, order IDs, customer names, internal repo names, private ticket IDs, and exact private URLs.
4. **Is this a durable mechanic?** Keep selectors, route shapes, button labels, public endpoint paths, and wait conditions. Replace concrete values with placeholders.

### Bad

```markdown
POST /api/workspaces/acme-prod/orders?session=eyJ...
Cookie: sessionid=abc123
Click the row for jane@example.com's order ORD-928173.
```

### Good

```markdown
POST /api/workspaces/<workspace>/orders
The list page hydrates through `/api/workspaces/<workspace>/orders`; wait for the table body to contain at least one row before using row actions.
```

## Promotion Rule

A note graduates into a domain skill only when it is reusable across future tasks for the same host. If it is just today's breadcrumb, keep it in task notes instead.
