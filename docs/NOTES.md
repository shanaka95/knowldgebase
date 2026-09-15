# Notes: what people add that the document does not say

A scanned invoice cannot tell you it was already disputed. A policy PDF cannot
tell you which team it actually applies to, or that it was superseded in March.
Notes are where that goes.

A note has an author and a time, and it is **indexed with the page**: you can
find a page by searching for what somebody wrote about it, and an answer can
quote it.

## Where a note comes from

| Where | How |
|---|---|
| The page itself | The **Notes** section under the content — always there, empty or not |
| Uploading | The **Notes** field in the upload dialog, kept as the page's first note |
| The API | `note` on `POST /documents/`, or the `note` form field on any `/imports` route |
| An agent or MCP | The same two, through the account the key belongs to |

A note added at upload is written **before** the first index runs, so the page
is embedded once rather than twice for one upload.

## Content, or about content?

Both, deliberately, and the split is the whole design:

* **About**, for reading. A note is rendered as somebody's addition, under the
  page, with who wrote it and when. A scan should still read as the scan.
* **Content**, for finding. A note is in the page's search vector, in its
  document-level embedding, and in the excerpt Ask reads. A note nobody can
  find by searching for it is a note nobody will read again — and "why did we
  keep this?" is exactly the kind of question people search for.

### How the finding half works

`Document.notes_text` is a denormalised copy of every note on the page,
maintained by `app/services/notes.py` and nowhere else. It exists because a
Postgres generated column may only reference its own row: the page's
`search_vector` cannot join to `documentnote`, so something has to put the text
where it can see it.

Three places read it:

| Path | Where |
|---|---|
| Keyword search | `Document.search_vector`, a generated column over title, content and notes |
| Vector search | `worker/pipeline.py` — notes join the document-level text **and** get a chunk of their own, so a note can be retrieved and cited rather than only raising the page's score |
| Ask | `ask.py` `_readable_text` — the excerpt handed to the model |

Writing a note **re-indexes the page**. One enqueue per write, not one per
note: embedding is the expensive half.

## Who may do what

| | Needs |
|---|---|
| Read | Whatever reading the page needs |
| **Write** | **Viewer** |
| Edit | The author, and nobody else |
| Delete | The author, or anybody who could edit the page |

Writing needs only viewer, and that is the deliberate one. A note is precisely
what you want from somebody who cannot edit the document — the person who
received the invoice, not the person who filed it. Requiring edit rights would
mean the people with the most to add are the ones who cannot.

Editing is the author's alone: putting words in somebody's mouth is worse than
not being able to fix a typo. Deleting is shared with editors, because an
editor has to be able to clear something that should not be there.

## Things to know

* **A copy carries the notes over**, attributed to whoever made the copy. A copy
  without them loses the part explaining why the page was worth copying.
* **Deleting a page deletes its notes.** Deleting an *account* does not: the
  note stays, with no author. A note is part of the page's history, and
  removing somebody should not silently edit what a page says.
* **Notes are not versioned.** They belong to the page, not to a snapshot of
  it, which is why they are hidden while an older version or a translation is
  on screen.
* **The migration rewrites `document.search_vector`**, which is the only way to
  change a generated column's expression in Postgres. On a large installation
  that is not instant and it holds an ACCESS EXCLUSIVE lock on `document` while
  it runs.
