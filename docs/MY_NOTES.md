# My notes: private, indexed, and yours alone

The knowledge base holds *pages*: long-lived documents in shared spaces. There
was nowhere to put a thought. Anything short, personal or half-formed either
became a page in a shared space, which is the wrong audience and the wrong
weight, or it went somewhere else entirely and out of reach of the thing that
is supposed to be able to answer questions about what you know.

Notes are that place. A note is **private to whoever wrote it**, always, with
no share model and no superuser bypass. It still lives in a Space, it is still
indexed, and by default Ask and Search read it alongside pages.

> Not to be confused with `docs/NOTES.md`, which is the older feature: remarks
> people leave *on a page*. Those are shared with the page. These are not
> shared with anybody. They have separate tables, routes and interfaces.

## What a note is

| Kind | Body | Found by |
|---|---|---|
| **Text** | The editor's HTML | Its words |
| **Checklist** | One task list, ticked from the card | Its items |
| **Drawing** | Strokes, plus a rendered picture | What a vision model says is in it |

All three write into one `content_text` column, derived on save. The search
vector, the indexer, the lexical source and the reranker read that column and
nothing else, which is what keeps one pipeline for three kinds.

Beyond the body: **pin**, **archive**, **clone**, **tags**, a Space to file it
in, and a **reminder** that emails it to you.

## Privacy, and what it rests on

One rule: every query carries `Note.user_id == user.id`, and there is no
exception for anybody.

* Access goes through exactly one function, `services/user_notes.py:owned_note`.
  There is no helper in `core/permissions.py`, deliberately: a helper there
  invites the next person to reach for `accessible_documents_filter` beside it,
  which would hand notes to everyone in the space.
* **404, never 403**, including for a superuser, and including for somebody
  who administers the space the note is filed in. A 403 confirms the note
  exists, which turns every endpoint into an oracle.
* In Qdrant, a note point carries `owner_id`, and the note filter takes
  `owner_id` as a keyword argument with no default, so "search notes without
  saying whose" does not type-check.
* Hydration re-applies the owner filter in SQL, after the vector store has
  already filtered on it.
* A drawing is stored as a `NoteAsset`, never an `Attachment`: the attachment
  check falls back to the namespace for a file with no document, which would
  make a sketch downloadable by every member of the space.

`backend/tests/api/routes/test_user_notes_privacy.py` is the reason to believe
all of that. Its fixture is the hardest case: the note is filed in a space
somebody else *owns*.

## How soon a note is findable

| | When |
|---|---|
| By keyword | **The instant it saves.** Postgres writes the `tsvector` at COMMIT. |
| By meaning | A few seconds. Debounce (3s) plus one poll plus one embedding call. |

Indexing a note does not chunk with an LLM and does not write a summary. That
is right for a page somebody will read in a year and absurd for a shopping
list: two chat calls to index eleven words. A note costs one embedding call.

## Deleting a space does not delete your notes

`namespace_id` is `SET NULL`. `CASCADE` would let a space admin destroy other
people's private notes by deleting a space. `RESTRICT` would fail the delete
with "3 notes are in here", which tells that admin somebody has private notes
and is exactly the leak this is built to prevent. A note whose space is gone
reads as **Unfiled**, which is a state the interface can show.

## Archive is not delete

Archiving takes a note off the board and pauses its reminder. It does **not**
remove it from search, and it deletes no vectors: the whole point of putting
something away is being able to find it again. Delete is the irreversible one,
and it is also what frees a place against `max_notes`.

## Reminders

A reminder stores a **wall clock and an IANA zone**, not an instant, and every
occurrence is derived from the *anchor* rather than from the one before it.
Those two choices are the design:

* A "9am daily" reminder stays at 9am across a daylight-saving change. Adding
  24 hours to an instant does not.
* A monthly reminder on the 31st returns to the 31st in March. Derived from the
  previous occurrence it would clamp to 28 February and stay there for ever.

Sending is **at most once, by construction**: the claim, the delivery row and
the advance happen in one transaction, and the mail goes out after it commits.
A crash between the two loses an occurrence rather than sending two. After an
outage only the latest missed occurrence fires, once, with the ones it stood in
for counted on the delivery row.

A reminder is skipped and paused, never sent, when the note is archived, the
account is inactive, or the address is unverified.

## Dictation

`POST /notes/transcriptions` returns **text, not a note**. That makes "the
transcription worked but the note did not save" impossible rather than
something to compensate for, which matters because the credit balance is a live
function of the usage rows and there is nothing to refund against. It also lets
the same call dictate into an existing note, a checklist line or the search box.

* Billed per second of audio, at about **a credit a minute**, which is
  cost-parity with the token rate to within a tenth.
* **The audio is never stored.** It exists for one request. The value is the
  text; a voice brings retention obligations nobody asked for; and a note is
  private, so there is nobody to play it back to.
* Optional. With no `TRANSCRIPTION_MODEL` configured the microphone is not
  offered at all.

## Search and Ask

Notes are their own RRF sources rather than being ORed into the document
filter. A nested `should` of two `must` branches is exactly the shape where a
permissive mistake hides, and in a mixed ranking a dozen notes never place
against a hundred thousand document chunks. As a separate source, a note
ranked first among notes contributes what a document ranked first does.

**The API default is `false`; the interface sends `true`.** A client generated
before notes existed can never receive a note hit and mis-link it, and API-key,
MCP and agent callers do not silently start answering from private notes. A
bot quoting your grocery list to a colleague is a product decision nobody made.

## Limits

Notes have their own `max_notes`, resolved through the same four tiers as every
other limit: the account, its group, the default group, a constant. Archived
notes count, because they still hold rows, chunks and vectors.
