# Limits: what an account is allowed

An account may create a bounded number of pages — 100 by default. Administrators
raise or lower that for one person, or for a whole class of people at once by
putting them in a group.

**The people in a group are never told.** A group is an administrative device;
an account that reaches a limit is shown its own number, which it can act on,
and never the group the number came from, which it cannot.

## How a number is resolved

Four tiers, most specific first:

```
the account's own override
  → the group it is in
    → the default group
      → a built-in constant
```

`NULL` at any tier means **inherit from the one below**. That is the whole
design: a non-null column with a default cannot express "no opinion", so it
could never inherit, and "clear this override" would be unsayable.

Two consequences worth stating:

* **The default group is the floor for everyone**, not only for the unassigned.
  A group that leaves a number blank falls through to the default group rather
  than past it to the constant — so raising the default lifts exactly the people
  who were never given a number of their own.
* **`0` is a real answer.** "This account may not create pages" is a thing an
  administrator can say, and it is not the same as "inherit". Every check in
  `app/services/quota.py` is `is not None`, never truthiness.

An account with no group resolves against the default group. That is deliberate
rather than incidental: users are created in four places, one of which builds
`User(...)` by hand (`app/api/routes/private.py`, which is also where every
Playwright test user comes from). If membership had to be assigned at creation,
that path would quietly produce accounts outside the system.

## What is limited

| Key | Default | What it counts |
|---|---|---|
| `max_pages` | 100 | Pages this account created, wherever they live |
| `max_shares_per_document` | 50 | People one page is shared with, counting invitations |
| `max_members_per_space` | 50 | People in one space, counting invitations |

The last two predate groups and were per-account columns with no interface;
they now resolve through the same chain and are administrable for the first time.

Note the two subjects are different, deliberately. A **page** counts against
whoever created it, so a page you write in someone else's shared space is yours;
a **share** limit belongs to whoever owns the space, because it is their content
being handed out.

## Where the page limit is enforced

There are three ways a page comes into being and several ways to queue one, and
a check on only the first would be no check at all:

| Path | Where |
|---|---|
| Writing one | `documents.py` `create_document` |
| Copying one | `documents.py` `clone_document` — needs only *viewer* on the original, so without a check it is an unmetered way to fill the base |
| Importing one | `worker/queue.py` `create_document_from_import` |
| Queueing an import | `imports.py` (single, combined, batch), `data_sources.py` (Drive), and `retry_import` |

**A queued import counts as the page it is about to become.** Otherwise a limit
of a hundred is no limit: you queue five hundred files and collect them later.
This is the same reasoning that makes an unaccepted invitation count against a
share limit.

The upload check runs **before anything reaches object storage**. A check beside
the job insert would be correct and still wrong — the files are stored first, so
twenty of them would be pushed into MinIO and then refused, leaving objects
nothing will ever collect.

The worker checks **again** before it creates the page, because a job can outlive
the limit it was queued under. A job refused there is failed, not retried: a
limit does not become untrue on a second attempt.

## Administering it

`/admin` → **Groups**. Superuser-only, and session-only — the dependency chains
off `SessionUser`, so an API key cannot reach it even with a superuser's key.

* Create a group and give it numbers. Leave a box blank and it inherits; the
  greyed placeholder shows what its members would get anyway.
* The default group cannot be deleted. Deleting any other returns its members to
  the defaults, which is what "no group" already means.
* **Users** tab: each row shows the group and `used / limit`, with an *Override*
  badge when the number is that account's own. "Group and limits" on a row opens
  both together — they are one decision, so they are one request.

Overrides are sent as a **complete map**, not a patch: a key that is absent is an
override that is not set. That is what an empty form field naturally produces,
and it removes the three-way muddle between "not sent", "sent as null" and
"sent as a number".

### Adding a limit later

Four lines and a short migration: a nullable column on `user` and on
`usergroup`, one entry in `LIMITS` in `app/services/quota.py`, and a field on the
admin schemas. The resolver, the serialiser and the admin form all read the
registry — the form is *generated* from `GET /admin/user-groups/limits`, so a new
setting appears in the interface without the interface changing.

## Things to know

* **Deleting a page frees its place immediately.** Pages are hard-deleted, so the
  count is a live `count(*)` with no tombstones. A stored counter would drift on
  every delete, cancelled import and deleted account.
* **Turning this on can put an existing account over its limit.** Nothing is
  deleted and nothing stops working — they keep every page and can read and edit
  all of them; they just cannot add another until they delete one or an
  administrator raises the number. Worth checking who is affected before
  deploying:
  ```sql
  SELECT created_by, count(*) FROM document GROUP BY 1 ORDER BY 2 DESC LIMIT 10;
  ```
* **Administrators start with a large allowance** (`100000`), applied as an
  ordinary override rather than an exemption in the resolver — so it shows up in
  the admin table like anyone else's and can be lowered. Whoever runs an
  installation should not be locked out of it by a number that did not exist
  yesterday.
* **A page whose author was deleted counts against nobody.** An import whose
  owner went away mid-flight still completes; refusing it would punish no one.
