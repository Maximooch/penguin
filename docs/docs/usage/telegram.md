---
title: Telegram
---

# Telegram bot

Penguin can run `@Penguin_agent_bot` as an optional Telegram surface over the
same core used by `penguin-web`. The current implementation covers Phases 0–5:
DMs, allowlisted groups and forum topics, stable Penguin sessions, streaming,
basic media, questions and approvals, polling or authenticated webhooks, and
restart-safe SQLite ingress and delivery.

Voice transcription, TTS, audio/video and broad media support, reactions,
scheduled delivery, and general proactive/background sends are later phases.

## Requirements and installation

Telegram uses `python-telegram-bot==22.6` as an optional dependency.
That dependency is enabled only on Python 3.10 or newer; use Python 3.10–3.12
for Penguin's Telegram integration.

```bash
# Published package
pip install "penguin-ai[telegram]"

# Source checkout
uv sync --extra telegram
```

The base Penguin install does not install or start Telegram support.

## Create and secure the bot

1. Open Telegram's official [BotFather](https://t.me/BotFather).
2. Create or manage the bot whose username is `@Penguin_agent_bot`.
3. Keep its HTTP API token in a secret manager or process environment.
4. If a token is ever exposed, revoke it with BotFather and issue a new one.

With `expected_username: Penguin_agent_bot`, Penguin verifies the username
returned by Telegram at startup and refuses to start the integration if it does
not match (case-insensitive).

Never paste a live bot token or webhook secret into YAML, source control,
documentation, logs, issue trackers, or chat. Penguin accepts the bot token only
from `TELEGRAM_BOT_TOKEN` and the webhook secret only from
`TELEGRAM_WEBHOOK_SECRET`.

For an interactive local shell, this reads the bot token without echoing it:

```bash
read -s TELEGRAM_BOT_TOKEN
export TELEGRAM_BOT_TOKEN
```

For a service, inject the variable through the service manager or secret store.

## Start with default-deny configuration

Add a `channels.telegram` block to the YAML configuration Penguin loads. Start
disabled with empty numeric allowlists:

```yaml
channels:
  telegram:
    enabled: false
    expected_username: Penguin_agent_bot
    transport: polling
    token_env: TELEGRAM_BOT_TOKEN

    dm_policy: allowlist
    allow_from: []

    group_policy: allowlist
    group_allow_from: []
    group_sender_allow_from: []
    activation: mention
    groups: {}
    open_access_acknowledged: false

    streaming:
      mode: progress
      edit_interval_ms: 750
      include_reasoning: false

    media:
      max_download_mb: 20
      max_document_text_chars: 100000

    permissions:
      mode: workspace
      approvals: prompt
      timeout_seconds: 300
      allow_yolo: false

    delivery:
      retry_attempts: 8
      retry_base_seconds: 1
      retry_max_seconds: 300
      dead_letter_after_hours: 24

    runtime:
      poll_timeout_seconds: 30
      request_timeout_seconds: 30
      ingress_workers: 2
      delivery_workers: 2

    webhook:
      public_url: null
      path: /api/v1/integrations/telegram/webhook
      secret_env: TELEGRAM_WEBHOOK_SECRET
      timeout_seconds: 10
      body_limit_bytes: 1048576
```

Use `/whoami` to obtain numeric Telegram IDs after temporarily authorizing a
known account, or inspect them with Telegram's normal bot administration tools.
Usernames are never authorization identities.

For a personal polling bot:

1. Put your positive numeric user ID in `allow_from`.
2. Leave both group allowlists empty until group access is needed.
3. Export `TELEGRAM_BOT_TOKEN`.
4. Change `enabled` to `true` and start `penguin-web`.

```bash
HOST=127.0.0.1 PORT=9000 penguin-web
```

The manager starts and stops with the web application's lifespan; it does not
create a second Penguin core.

## Authorization policies

DM policy choices are:

- `allowlist`: only positive IDs in `allow_from` are admitted.
- `pairing`: an operator creates a one-hour, single-use code; the user sends
  `/pair CODE` in a private chat.
- `disabled`: no DMs are admitted.
- `open`: all DMs are admitted, but only when
  `open_access_acknowledged: true` is also present. This is discouraged for a
  tool-using coding agent.

Group access requires two independent checks when `group_policy: allowlist`:

- `group_allow_from` contains the numeric group or supergroup chat ID, normally
  a negative number.
- `group_sender_allow_from` contains each positive user ID allowed to invoke
  Penguin in those groups.

An allowed group with an unlisted sender still cannot start a Penguin turn.
`group_policy` also accepts `disabled` or explicitly acknowledged `open`.

Trusted execution defaults can be bound to a group and refined per forum topic:

```yaml
channels:
  telegram:
    groups:
      "-1001234567890":
        enabled: true
        require_mention: true
        history_limit: 50
        prompt: Keep answers concise and operational.
        directory: /absolute/path/to/project
        agent_id: null
        mode: plan
        skills: [ponytail]
        topics:
          "42":
            require_mention: false
            history_limit: 10
            prompt: null
            mode: build
            skills: []
```

Group and topic rules inherit deterministically. A disabled group cannot be
re-enabled by a topic. Directories must already exist and be absolute; invalid
configuration stops startup. A configured skill that is unavailable in
Penguin's trusted skill catalog fails that turn instead of being ignored.

These trusted defaults are copied into the durable address binding when that
group or topic is first used. `/new` creates a fresh session and reloads the
configured directory, agent, mode, prompt, skills, activation, and history
limit. `/mode` and `/activation` intentionally change the current binding until
the next `/new`.

Updates that fail authorization are dropped before durable admission and do not
receive a denial message. The only pre-authorization exception is a valid,
single-use `/pair` code in a private chat.

## Groups, privacy mode, and forum topics

Groups default to `activation: mention`. Penguin runs only when a message
mentions `@Penguin_agent_bot`, addresses a command to it, or replies to the bot.
An authorized user can change a group's or topic's binding with
`/activation mention` or `/activation always`.

Telegram's [privacy mode](https://core.telegram.org/bots/features#privacy-mode)
controls which group updates Telegram sends to a bot. Mention activation works
with privacy mode. `activation: always` can act only on updates Telegram actually
delivers; if ambient group context is required, review the risk and change the
bot's privacy setting with BotFather. Numeric group and sender authorization
still applies when privacy mode is disabled.

Each private chat, group, and forum topic has a separate durable address and
Penguin session binding. Replies, typing indicators, previews, callbacks, and
final messages preserve the topic ID. `/topic` shows the current topic and
session binding. Group history supplied to a turn is bounded and includes only
messages visible to the bot.

Commands addressed to another bot are ignored. Supergroup ID migrations move
the stored binding to the new chat ID.

## Polling and webhooks

### Polling

`transport: polling` is the default. Penguin durably stores each normalized
update before advancing the Telegram polling offset. A token fingerprint and
lease prevent two Penguin pollers from owning the same bot; a polling conflict
stops the poller and appears in status instead of being hidden.

Use one running polling instance per bot token.

### Webhook

Webhook mode uses the same durable ingress path. Set an externally reachable
HTTPS base URL and generate a strong secret in the environment:

```bash
TELEGRAM_WEBHOOK_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
export TELEGRAM_WEBHOOK_SECRET
```

```yaml
channels:
  telegram:
    enabled: true
    transport: webhook
    webhook:
      public_url: https://penguin.example.com
      path: /api/v1/integrations/telegram/webhook
      secret_env: TELEGRAM_WEBHOOK_SECRET
```

Route that path through the reverse proxy to `penguin-web`. Penguin registers
the webhook with Telegram's `secret_token`; the route compares
`X-Telegram-Bot-Api-Secret-Token` in constant time, applies configured body and
adoption time limits, and returns success only after durable adoption. See
Telegram's official [setWebhook documentation](https://core.telegram.org/bots/api#setwebhook)
for network requirements.

Polling and webhook ownership are mutually exclusive. Change `transport` and
restart Penguin rather than running both for one token.

## Commands

The bot registers this command menu:

| Command | Behavior |
| --- | --- |
| `/start`, `/help` | Show the available Telegram commands. |
| `/new` | Create and bind a fresh Penguin session for this chat or topic. |
| `/status` | Show the bound session and mode. |
| `/stop` | Abort the active Penguin turn for the bound session. |
| `/whoami` | Show numeric user, chat, and topic IDs. |
| `/session` | Show the bound Penguin session ID. |
| `/mode plan`, `/mode build` | Show or change the binding's agent mode. |
| `/model` | Show the active model. |
| `/goal ...` | Use Penguin's session-goal command for the bound session. |
| `/project` | Show the bound project directory. |

Additional policy commands are `/pair CODE`, `/activation mention|always`, and
`/topic`. A command explicitly addressed to another bot is ignored.

## Streaming and media

Text is rendered as safe Telegram HTML with plain-text fallback and split at a
conservative 4,000 UTF-16 code units. The streaming modes are:

- `off`: typing indicator followed by the final response.
- `progress`: one `Penguin is working…` message, replaced by the final response.
- `edit`: throttled, coalesced assistant previews followed by the final response.

Reasoning is hidden by default. Enable `include_reasoning` only when everyone
with access to the destination is allowed to see model reasoning.

Current inbound media support is deliberately narrow:

- validated Telegram photos, passed through Penguin's image input path;
- bounded UTF-8 text documents with supported text, JSON, XML, YAML, CSV, or
  Markdown MIME types;
- captions and reply-to text as untrusted input context.

The default download limit is 20 MiB and can be configured from 1–50 MiB.
Document text defaults to 100,000 characters and is capped at 1,000,000.
Temporary downloads are removed after success, failure, or cancellation.
Files explicitly marked with Penguin's `publish_artifact` tool are delivered as
photos or documents when they exist under the bound project, fit the same size
limit, and remain safe at send time. Ordinary reads and writes are never
auto-attached.

Unsupported or oversized media receives a visible rejection and leaves no
temporary file. Transport or delivery failures remain available through the
operator dead-letter diagnostics. Voice messages, transcription, TTS, audio,
video, media groups, and general file ingestion are not implemented in Phases
0–5.

## Questions, approvals, and remote permissions

Penguin projects pending questions into Telegram with inline choices; the
authorized user may also answer with text. Tool approval prompts have
`Approve once` and `Deny` buttons. Callback records are scoped to the originating
bot account, chat, topic, and user, expire after the configured timeout, and can
be completed only once. An approved waiter resumes the intended tool operation
at most once. When Penguin asks several questions together, answer with exactly
one non-empty line per question; inline choices are offered only for a single
question. Resolution, expiry, shutdown, and restart replace active controls with
a terminal state so stale buttons cannot resume work.

Remote permissions remain subordinate to Penguin's instance security mode:

- `permissions.mode` accepts `read_only`, `workspace`, or `full_access`, but is
  capped by the instance-level `security.mode`.
- `permissions.approvals: prompt` waits for Telegram approval; `deny` refuses
  operations requiring approval.
- `publish_artifact` is an explicit, approval-gated network operation; Penguin
  never infers outbound files from ordinary path-looking tool output.
- `allow_yolo: true` is rejected.
- An enabled Telegram integration refuses to start when `PENGUIN_YOLO` is true
  or Penguin security enforcement is disabled.

Telegram access is not permission to bypass Penguin's tool policy.

## Persistence, recovery, and delivery semantics

Channel state lives in
`{PENGUIN_WORKSPACE}/channels/channel_state.db` and includes address/session
bindings, hashed pairing codes, DM grants, single-use callbacks, ingress,
deliveries, and polling ownership. Protect this database: bounded payloads may
contain private message text, error details, and local artifact paths. Raw bot
tokens and webhook secrets are not stored.

Set `PENGUIN_WORKSPACE` or `workspace.path` to a durable, private location.
An ephemeral workspace such as `/tmp` defeats restart recovery.

Completed rows are retained to preserve deduplication and diagnostics. Individual
payloads and unauthorized admission are bounded, but Phases 0–5 do not expose
automatic age-based pruning; monitor the channel database on long-lived
installations and protect it with the same retention discipline as conversation
data.

The Phase 5 reliability contract is:

- update IDs are deduplicated before execution;
- polling admission and offset advancement are one SQLite transaction;
- one chat/topic lane stays ordered while independent lanes can progress;
- completion and final-delivery enqueue are atomic;
- retryable Telegram failures honor `retry_after` and bounded backoff;
- expired unstarted claims retry after restart;
- expired delivery leases return to the outbox;
- fatal or exhausted work becomes an inspectable dead letter.

:::warning Execution-uncertain ingress

If Penguin crashes after a turn is marked started, a non-idempotent tool may
already have run. Recovery marks that ingress dead with
`error_class: execution_uncertain` instead of executing it automatically.
Inspect the original request and its effects before manually retrying; retrying
runs the turn again.

Likewise, an outbound retry can rarely duplicate a Telegram message if Telegram
accepted it but the local process died before recording the acknowledgement.

:::

## Operator API

The status, pairing, and dead-letter routes use Penguin's normal web API
authentication. The webhook route is the only Telegram route authenticated by
the separate Telegram webhook secret. The examples below assume an API key in
`PENGUIN_API_KEY`.

```bash
# Redacted status: never returns bot/webhook credentials
curl http://127.0.0.1:9000/api/v1/integrations/telegram/status \
  -H "X-API-Key: $PENGUIN_API_KEY"
```

For `dm_policy: pairing`, create a one-hour, single-use code, optionally pinned
to one expected numeric user ID:

```bash
curl -X POST http://127.0.0.1:9000/api/v1/integrations/telegram/pairings \
  -H "X-API-Key: $PENGUIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"expected_user_id":"123456789","ttl_seconds":3600}'
```

Send the returned code to the intended user through a trusted channel. They
complete pairing by sending `/pair CODE` privately to the bot. Revoke the grant
with:

```bash
curl -X DELETE \
  http://127.0.0.1:9000/api/v1/integrations/telegram/pairings/123456789 \
  -H "X-API-Key: $PENGUIN_API_KEY"
```

List dead ingress or delivery records:

```bash
curl "http://127.0.0.1:9000/api/v1/integrations/telegram/dead-letters?kind=ingress&limit=50" \
  -H "X-API-Key: $PENGUIN_API_KEY"
```

Dead-letter payloads can contain private input and paths; expose this operator
API only to trusted administrators. Retry or discard one reviewed record:

```bash
curl -X POST \
  http://127.0.0.1:9000/api/v1/integrations/telegram/dead-letters/retry \
  -H "X-API-Key: $PENGUIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"kind":"ingress","record_id":"RECORD_ID"}'

curl -X POST \
  http://127.0.0.1:9000/api/v1/integrations/telegram/dead-letters/discard \
  -H "X-API-Key: $PENGUIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"kind":"delivery","record_id":"RECORD_ID"}'
```

Discard is allowed only for terminal records that no retained delivery still
references.

## Current boundaries

Phases 0–5 support one configured bot account in the `penguin-web` process.
They do not yet provide voice/TTS, broad Telegram media parity, reactions,
scheduled/home-channel delivery, proactive background delivery, or a Telegram
operator CLI. Use the authenticated operator API for status, pairing, and dead
letters until later phases add broader operational surfaces.
