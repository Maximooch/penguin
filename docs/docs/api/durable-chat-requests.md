# Durable Link chat requests

Penguin can persist acceptance and results for chat requests from the trusted Link service.
Ordinary chat requests keep their existing behavior.

## Contract

`GET /api/v1/link/capabilities` advertises `durable_chat_requests.version: 1`.
The capability includes the lookup endpoint, `/api/v1/link/chat-request`.
Both endpoints require the dedicated Link service credential.

An opted-in `POST /api/v1/chat/message` includes:

- `durable_request: true`
- An explicit `session_id` and `client_message_id`
- A valid Link execution descriptor and the dedicated Link service credential

The identity is the pair `(session_id, client_message_id)`.
Penguin compares a hash of the validated request fields, including execution authority.
A retry with different fields returns HTTP 409 and `CHAT_REQUEST_IDEMPOTENCY_CONFLICT`.
Callers must preserve the original request fields across retries.

Penguin commits acceptance before it starts the existing chat pipeline.
Only the first claim executes that pipeline.
Concurrent retries cannot execute a second copy.
An HTTP disconnect does not cancel the independent execution task.

## Lookup and recovery

The lookup endpoint accepts `session_id` and `client_message_id` query parameters.
It returns one of these receipts:

| State | Meaning | Safe caller action |
| --- | --- | --- |
| `absent` | This database has no acceptance record. | Submit the original request with the same identity and fields. |
| `accepted` | Penguin committed acceptance but has no persisted result. | Observe or reconcile the original execution. Do not start a replacement. |
| `completed` | Penguin persisted the HTTP result. | Read the `response` object and interpret its runtime status. |

A completed receipt does not independently prove successful agent work.
Its response can describe an error or another runtime status.
A duplicate POST returns the persisted response when one exists.
Otherwise, it returns `status: recovering` and `request_state: accepted`.

## Storage and limits

Receipts live in `chat-requests.sqlite3` under the runtime workspace.
All processes that serve the same requests must use the same database.
The database stores request hashes and results, not the original request payloads.
Receipts have no automatic expiry.

This contract prevents duplicate execution after a Link crash or a lost acknowledgement.
It does not resume arbitrary tools after a Penguin process crash.
A crash after acceptance, or a failed result write, leaves the receipt accepted.
No timeout or lease converts that uncertainty into permission to execute again.
Automatic reconciliation of those cases remains separate work.

CAUTION: Do not remove the receipt database while clients can retry old requests.
Removal loses the evidence that prevents duplicate execution.

## Verification

The offline tests cover concurrent claims, conflicting reuse, disconnects, restart lookup, failed result writes, immutable results, and authenticated HTTP behavior.

```sh
python -m pytest tests/web/test_chat_requests.py tests/web/test_link_execution_authority.py -q
```
