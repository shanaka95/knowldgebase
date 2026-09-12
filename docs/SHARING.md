# Sharing

Ways to let somebody else in, and one rule that runs through all of them:
**access is granted to a confirmed identity, or to nobody.**

A **page** and a **space** are shared the same way, deliberately - the same
request shape, the same three outcomes, the same invitation machinery - because
they are the same act at different scales, and an interface that treats them
differently makes people learn two things instead of one.

What differs is how much is being handed over. A page is one page. A space is
everything in it, **including pages added later**, which is why sharing a space
needs space admin while sharing a page needs only editor.

| | Who gets in | How access ends |
|---|---|---|
| Share a page with a person | one account, named by email | the share is removed |
| Share a space with a person | one account; everything in the space, now and later | they are removed from the space |
| Invite an address | nobody yet - it becomes access when that address is confirmed on an account | the invitation is withdrawn, or it expires |
| Share a page by link | anyone holding the link, without signing in | the link is withdrawn |
| Copy | nobody - the copy belongs to whoever made it | not applicable |

Sharing a **page** is a grant on that page alone. It never gives access to the
space around it, the folder it sits in, or anything beside it. That is asserted
in `tests/api/routes/test_isolation.py::test_sharing_one_page_does_not_share_the_space`.

## Telling the two apart

Somebody who has been given things needs to know which kind each one is, so the
API says so rather than leaving it to be inferred:

* `NamespacePublic.shared_with_you` is true for a space that belongs to somebody
  else. Shared spaces still appear in the space list and are still selectable -
  they are yours to work in - but they are marked, because writing into one puts
  content in another person's knowledge base.
* `SharedWithMe` returns `namespaces` and `documents` separately. A whole space
  and a single page are different grants with different risks.
* A page shared on its own carries `namespace_name`, so it can be shown where it
  came from without that granting any access to the space.

## Finding the person

`GET /users/lookup?email=` answers whether one **exact** address has an account.
Exact matches only, never prefixes, and only for someone signed in.

Confirming an address somebody already typed is what sharing needs. A prefix
search would be a different thing entirely: a way to read the user list one
keystroke at a time. The interface therefore waits until what has been typed is
a complete address before it asks.

## Sharing with people

```
POST /documents/{id}/shares/batch
  { "emails": [...], "role": "viewer" | "editor", "message": "optional note" }

POST /namespaces/{id}/members/batch
  { "emails": [...], "role": "viewer" | "editor" | "admin", "message": "..." }
```

Batched, because the interface asks for several addresses at once and has to
report back which were known and which will be invited - something it cannot do
one call at a time without inventing its own error handling. The reply separates
the three outcomes so it can say so plainly:

* `shared` - the address had an account. Access now, plus an email saying who
  shared what.
* `invited` - no account yet. No access, plus an email inviting them.
* `skipped` - with a reason: your own address, somebody who already has the
  space, or the page's limit reached.

The optional `message` is quoted into the email in the sharer's own words. It is
**escaped, never rendered as markup**: it is text written by one person and
displayed to another, which is exactly the shape of a cross-site scripting bug
if treated casually.

### How many people

A page can be shared with at most `user.max_shares_per_document` people, and a
space with at most `user.max_members_per_space` - **50 each by default, and set
per account** so they can follow a plan later without another migration. They
are separate numbers because they are separate decisions: a space is a bigger
thing to hand over.

The limit belongs to whoever owns the space: it is their content being
distributed, whoever pressed the button.

Pending invitations count towards it. Otherwise a thousand invitations would
slip under a limit of two and only bite once people started signing up.

## Inviting somebody who is not here yet

An invitation is **not access**. It is a record that somebody meant to share a
page with an address, and an email saying so.

```
share  ->  invitation recorded  ->  email sent  ->  they register
                                                          |
                                          they confirm the address
                                                          |
                                              the share is created
```

The link in the email carries a token, stored only as a SHA-256 hash like every
other one-time secret here. **The token grants nothing.** Someone who guesses
one can read what the invitation is about - who shared which page, which the
recipient already knows from the email - and nothing else. Opening the page
requires an account on that address, confirmed.

Consequences worth stating:

* Registering with a *different* address than the one invited grants nothing.
  The invitation names an address; confirming another proves nothing about it.
* An expired invitation does nothing, and says so rather than failing silently.
* Withdrawing an invitation kills the emailed link immediately.
* Re-inviting the same address replaces the previous invitation rather than
  stacking another beside it, so the newest email is the one that works.

Invitations live for `SHARE_INVITE_TTL_DAYS` (14): long enough to survive a
holiday, short enough that a forwarded mailbox from last year is not a way in.

## Sharing by link

```
POST /documents/{id}/public    -> { slug, url }
DELETE /documents/{id}/public  -> the link is dead
GET /public/documents/{slug}   -> the page, to anyone
```

The link is the only credential, so it is treated as one:

* The identifier is a **random slug**, not the page id. Withdrawing and sharing
  again produces a *different* link, so an address someone kept does not quietly
  come back to life.
* Publishing twice keeps the existing link, because re-opening the dialog to
  copy the address again should not break the copy already sent.
* A public page gives away **nothing around it**: no space, no folder, no
  neighbouring pages, no author ids, no version history.
* Images embedded in the page are served through the page's own slug, and only
  if the page actually references them. Publishing a page does not publish the
  space's file store.
* Only somebody who may share the page may publish it. A guest editor cannot
  publish somebody else's page to the world.

A published page's own id also works as the identifier, because a page that is
public is public - its id is no more secret than its slug. A page that is *not*
currently published is simply not found there, which is what makes withdrawal
immediate.

## Copying

```
POST /documents/{id}/clone  { "namespace_id": ..., "folder_id": ..., "title": ... }
```

Anyone who can read a page can copy it into a space they can write to. The copy
belongs to them and is a separate page from the moment it exists: editing it
does not touch the original, the original's shares do not follow it, and nobody
else can see it until its new owner shares it.

This is how somebody keeps a page that was shared with them. A share can be
changed or withdrawn at any time; a copy cannot.

**Images come too.** Each embedded attachment is copied into the destination
space and the markup is rewritten to point at the copy. Leaving the copy
pointing at the original's files would render for the person who already had
access and break for everybody else - which is most of the reason to copy in the
first place.

## Through MCP

An assistant sees exactly what its key's owner sees, and is told which is which:

| Tool | |
|---|---|
| `list_shared_with_you` | pages other people shared, marked `shared_with_you` with `your_role` |
| `list_people_with_access` | who has access, and who is only invited |
| `share_page` | share by email, inviting anyone without an account |
| `share_space` | share a whole space, with a warning that it is the bigger grant |
| `list_space_members` | who is in a space, and who is only invited |
| `unshare_page` / `remove_from_space` | remove one person's access |
| `share_page_by_link` / `stop_sharing_by_link` | publish and withdraw, with an explicit warning |
| `read_public_page` | read a page shared by link, even one belonging to somebody else |
| `clone_page` | take a private copy |

`get_page` falls back to the public endpoint when a page is not the caller's, so
an assistant handed a link can read it without being given an account.

## What is tested

`tests/api/routes/test_sharing.py` (55 tests) covers all of it, including the
cases where the answer must be *no*: an invitation grants nothing on its own,
registering with a different address grants nothing, an expired or withdrawn
invitation does nothing, a withdrawn link stops working immediately, a
re-published page gets a new link, publishing one page does not publish its
neighbours or the space's files, a guest editor cannot publish, a copy is
invisible to the original's owner, and nobody can copy a page they cannot read.

For spaces it also covers the cases that must be *yes*: a shared space appears
in the space list marked as somebody else's, covers pages added after the share,
and shows up under "Shared with me" as a space rather than a heap of pages. And
the ones that must be *no*: only an admin may share a space onwards, the owner
is skipped rather than demoted, and a withdrawn space invitation stops working.
