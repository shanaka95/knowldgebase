# Accounts, sessions and access

PlusGPT is a personal knowledge base holding contracts, payslips and private
notes. Everything below follows from that: the cost of someone else getting in
is high, and the cost of an extra ten seconds at sign-in is low.

## Signing in takes two steps, always

A password buys a **challenge**, never a session. The session is issued only
after a code emailed to the account's own address is answered.

```
POST /login/access-token   (form: username, password)
   -> LoginChallenge { challenge_token, sent_to (masked), code_length, expires_at, delivered }

POST /login/two-factor     { challenge_token, code }
   -> Token { access_token }
```

There is no opt-out and no "remember this device". Both exist to reduce how
often the second factor applies, and a second factor that usually does not apply
is not a second factor. A reused or leaked password is then insufficient on its
own, which is the entire point.

The challenge token is not a credential. It carries a `typ` claim that the
session check rejects outright, so presenting it as a bearer token gets nowhere.
That check is not theoretical: without it the challenge *was* accepted as a
session, and the test that caught it is
`test_a_challenge_token_is_not_an_access_token`.

| | |
|---|---|
| Code | 6 digits, `TWO_FACTOR_CODE_LENGTH` |
| Lives for | 10 minutes, `TWO_FACTOR_TTL_MINUTES` |
| Guesses | 5, `AUTH_CODE_MAX_ATTEMPTS`, then the code is destroyed |
| Codes per 15 minutes | 5, `AUTH_CODE_MAX_SENDS` |
| Challenge lives for | 15 minutes, `LOGIN_CHALLENGE_TTL_MINUTES` |

Six digits is a million possibilities, which is plenty for a code that dies
after five wrong answers and ten minutes, and far too few for one that does not.

## An address is confirmed before it can sign in

Registering creates the account but not the ability to use it. Until
`email_verified_at` is set, `/login/access-token` answers 403 and the interface
offers to send the link again. Registering with someone else's address therefore
gains nothing.

The link confirms **the address it was sent to**. If the account moves to a
different address in the meantime, an older link proves nothing about the new
one and is refused.

## Nothing reveals whether an address is registered

`/users/signup`, `/login/verify-email/resend` and `/login/password-recovery` all
answer identically whether or not the address is known, and a wrong password is
indistinguishable from an unknown account. Anything else turns the sign-in page
into a tool for discovering who has an account here. The person who actually
owns the address finds out from their inbox.

Registering an address that is already taken quietly re-sends the confirmation
if the account was never confirmed, because that is almost always the same
person trying again after losing the first message. The existing account is
never modified.

## One-time secrets are never stored

Only a SHA-256 hash reaches the database, so a database copy does not let anyone
sign in. There is no key-stretching and none is needed: unlike a password these
are long random values, or short-lived digits with a hard guessing budget, not
something a person chose and reused elsewhere.

Issuing a new secret retires the previous one. Without that, every code ever
emailed would stay valid until it expired, and an old message would be as good
as a new one.

Three flows share one table and one set of rules:

| Purpose | Shape | Lives for |
|---|---|---|
| `verify_email` | long token in a link | 48 hours |
| `two_factor` | 6 digits | 10 minutes |
| `password_reset` | long token in a link | 60 minutes |

## Sessions can be ended

A JWT cannot be withdrawn once issued, so every account carries a
`session_epoch` and every token records the value it was minted under. Raising
the counter leaves every older token failing its check.

It is raised when:

* the password is changed (the caller is handed a replacement token, so they are
  not signed out of the browser they are sitting in front of as a reward for
  good hygiene),
* the password is reset through an emailed link,
* an administrator resets someone's password, which is usually a response to a
  compromise,
* `POST /login/sign-out-everywhere` is called.

## Brute force

Ten wrong passwords inside fifteen minutes locks an account for fifteen minutes,
counted in a rolling window (`LOGIN_MAX_FAILURES`, `LOGIN_FAILURE_WINDOW_MINUTES`,
`LOGIN_LOCKOUT_MINUTES`). Someone who mistypes twice a week is never locked out;
a script working through the top thousand passwords gets ten tries and a wall. A
successful sign-in clears the count.

## API keys, and how MCP fits

Programmatic callers - including the MCP server - use a personal API key rather
than a password. A key:

* belongs to exactly one user and reaches exactly what that user reaches,
* carries a scope, `read` or `write`,
* **cannot manage the account**: it cannot change the password and cannot mint
  more keys, so a leaked key cannot be used to take the account over,
* stops working the moment it is revoked.

This is what makes an MCP connection safe to hand to an assistant: it is scoped
to one person's spaces by construction, not by a rule someone remembered to
write. `tests/api/routes/test_isolation.py` asserts all of it, alongside the
whole cross-tenant surface - pages, spaces, folders, files, search, the AI index
and the users endpoints.

## Email

AWS SES, configured by `EMAIL_ENABLED`, `EMAIL_FROM`, `AWS_REGION`,
`AWS_ACCESS_KEY` and `AWS_ACCESS_SECRET`. With `EMAIL_ENABLED=false` - the
default, and how development and the test suite run - nothing is sent and codes
are written to the log, so every flow works offline.

Sending never fails a security decision. A provider outage must not be reported
as "wrong password", and must not leave someone waiting for a message that is
not coming either, which is why `LoginChallenge.delivered` exists and the
interface says so plainly.

An account with an unconfirmed address and a mail provider that is down is
locked out until the provider returns. That is the right trade: the alternative
is letting people in without confirming anything.
