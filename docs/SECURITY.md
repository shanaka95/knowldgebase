# Security

What is defended, how, and what was found when it was audited.

## The model

| Layer | Rule |
|---|---|
| **Sign-in** | Password **and** a code emailed to the address. A password alone is never enough. |
| **Lockout** | Wrong passwords are counted in a rolling window; too many locks the account for a period. Wrong codes burn a per-code attempt budget. |
| **Tokens** | JWT carrying a `session_epoch`, so *sign out everywhere* invalidates every issued token at once. |
| **API keys** | Stored hashed, shown once, scoped `read` or `write`. A `read` key is refused on every write. |
| **Account management** | JWT-only. An API key cannot reach `/users/me*`, `/api-keys*` or anything under `/admin/*`, **even a superuser's key** — those dependencies chain off `SessionUser`. |
| **Authorization** | Checked per request against the page or space, never cached into the token. Anything you cannot see is reported `404`, not `403`. |
| **Secrets at rest** | Passwords, API keys and auth codes hashed; data-source credentials encrypted. The API returns only whether a value is set. |
| **Edge** | HSTS, `nosniff`, `X-Frame-Options: DENY`, `frame-ancestors 'none'`. CORS admits one origin. |
| **Dev-only routes** | `/private/*` registers only when `FASTAPI_ENV=development`, which defaults to unset. It fails closed. |

## Spending limits

Two independent ceilings, both checked in real time, both resolving through
user → group → default group → constant:

* **Pages** — `docs/LIMITS.md`
* **Credits** — `docs/CREDITS.md`
* **Notes** — `docs/MY_NOTES.md`, which is private data rather than a limit,
  and is the one place where 404-not-403 is load-bearing against a superuser.
* **Marketing** — `docs/MARKETING.md`. Superuser only, and the one endpoint
  that answers without a credential is a POST precisely so that a mail scanner
  cannot spend it.

Every path that can reach a model is checked *before* the call: asking,
searching, uploading, Drive imports, translating, indexing in the worker, and
the agent proxy. Keyword search is never refused because it calls no model.

## Audit, September 2026

Findings, all fixed in the same change.

### 1. The agent proxy had no ceiling — *high*

`/agent-llm/v1/chat/completions` was **metered but not limited**. An agent
token could spend without bound, and the account behind it was never consulted.

Worse, three knobs went straight through to the provider:

* `n` and `best_of` — ask for many completions, pay for each
* `max_tokens` — unbounded, on every request

A shard runs somebody's prompt, so it is the least trusted thing here that can
spend money. It now resolves the owning account and refuses `402` when there is
nothing left; `n` and `best_of` are dropped, and `max_tokens` is clamped to
`AGENT_LLM_MAX_OUTPUT_TOKENS`.

### 2. A crafted Drive file id could steer the request — *medium*

`file_id` came from the client and was interpolated into a URL:

```python
f"{DRIVE_FILES}/{file_id}"
```

`httpx` resolves `..` against the base, so
`file_id="../../../oauth2/v1/tokeninfo"` sends the request — **carrying the
account's live OAuth token** — to a different Google endpoint entirely.

Constrained to `^[A-Za-z0-9_-]{1,255}$` in two places: on the request schema,
and again in the function that builds the URL.

> The first attempt used `Field(regex=...)`. **SQLModel accepts that keyword
> and silently drops it** — the constraint read as present and did nothing.
> Caught by testing the validator rather than trusting it, and replaced with an
> explicit `field_validator`. A control that looks present but is not is worse
> than no control.

### 3. Unbounded request body on the proxy — *low*

The proxy parsed whatever arrived. Now capped at `AGENT_LLM_MAX_BODY_BYTES`,
checked on the raw bytes *before* parsing — refusing after walking a hundred
megabytes of JSON has not saved anything.

### 4. Listing notes demanded write scope — *low, correctness*

`GET /documents/{id}/notes/` used `WriteAuth`, so a `read` key was refused a
read. Now `AuthDep`, like every other read.

### Checked and found sound

SQL (no string-built queries anywhere), storage keys (UUID paths, filenames
through `PurePosixPath(...).name`), attachment access (`_check_access` on both
read and download), public pages (an attachment is reachable only through the
slug of a page that references it; withdrawing a link is immediate),
privilege escalation (`UserUpdateMe` carries only name and email), mass
assignment on groups, the gateway control plane (shared secret compared with
`secrets.compare_digest`, fails closed when unset), `AskRequest` bounds, and
prompt templates (the only `.format()` calls take values from a fixed
language whitelist).

## Known and accepted

* **Prompt injection is inherent to RAG.** A page — or a note on one — can
  contain instructions aimed at the model. Answers cite the passages they were
  written from precisely so a reader can see where an answer came from.
* **Administrators can read content.** Stated in the privacy policy.
* **An account with no credits can still queue indexing jobs** by writing
  pages. Each fails at the worker's balance check, which is one query.
* **Concurrency overshoot.** Limits are checked at the start of an operation,
  so two simultaneous requests can both pass. The overshoot is bounded by one
  operation; the page limit takes an advisory lock where the overshoot would be
  large (imports).

## Reporting

Email **incident@plusgpt.io** before telling anybody else.
