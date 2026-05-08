# Cookies

Use cookies only when the task explicitly needs authenticated browser state. Treat
cookies as credentials: never print full values, never store them in reusable
skills, and never confuse cookies with page-local state such as `localStorage` or
`sessionStorage`.

## Browser Cookies Vs Page State

- **Browser cookies** are domain-scoped HTTP/browser credentials. HttpOnly
  cookies are invisible to page JavaScript but can be read through CDP cookie
  APIs.
- **Page state** (`localStorage`, `sessionStorage`, IndexedDB) is JavaScript
  storage. It is not sent automatically with every HTTP request unless site code
  reads it.
- If login state is missing, inspect both layers before assuming cookies are the
  issue.

## Read Cookies

Prefer CDP for browser-level cookies:

```python
cookies = cdp("Network.getCookies", urls=["https://example.com"])
for cookie in cookies.get("cookies", []):
    print(cookie["name"], cookie.get("domain"), cookie.get("sameSite"))
```

For page-state storage, use JavaScript explicitly:

```python
local_keys = js("Object.keys(localStorage)")
session_keys = js("Object.keys(sessionStorage)")
```

Do not dump raw cookie values into chat/logs. Summarize names, domains, counts,
and expiration status.

## Save Cookies

Save only when the user asked for persistence or profile migration. Redact values
unless writing to a secure local profile store:

```python
payload = cdp("Network.getCookies", urls=["https://example.com"])
# Persist payload securely outside reusable skills; do not paste values into logs.
```

Expected cookie fields usually include `name`, `value`, `domain`, `path`,
`expires`, `httpOnly`, `secure`, and `sameSite`.

## Set Cookies

Use CDP `Network.setCookie`/`Network.setCookies` for browser cookies:

```python
cdp(
    "Network.setCookie",
    name="session",
    value="<secret>",
    domain="example.com",
    path="/",
    secure=True,
    httpOnly=True,
    sameSite="Lax",
)
```

Then reload or navigate to the target origin so the site re-evaluates auth.

## Edge Cases

- `HttpOnly`: cannot be read or set from page JS; use CDP.
- `SameSite=None`: usually requires `secure=True`.
- Domain mismatch: `.example.com` and `app.example.com` are not equivalent for
  every flow.
- Expired cookies can appear in exports but will not authenticate.
- Third-party cookie blocking may prevent embedded auth flows.
