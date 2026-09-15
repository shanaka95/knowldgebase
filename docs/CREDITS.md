# Credits: one number for work priced three ways

A knowledge base spends money in three shapes — tokens through a chat model,
calls to an embedding model, calls to a reranker — and a limit expressed in any
one of them is meaningless for the others. A token limit says nothing about
reranking; a call limit treats a one-line question and a hundred-page import as
the same thing.

So there is one unit:

```
1 credit  =  1,000 tokens  =  10 embeddings  =  10 rerank calls
```

Everything is stored in **milli-credits**, which makes the arithmetic exact and
the rate trivial: **one token is one milli-credit**, and an embedding or rerank
call is a hundred. No floats near the ledger.

**Accounts start with 1,000 credits a month**, renewing on the 1st (UTC).

## What an account has

```
remaining  =  allowance + live grants − used this month
```

| Part | Where it comes from |
|---|---|
| **allowance** | `monthly_credits`, resolved through the same four tiers as every other limit: the account's override → its group → the default group → a constant |
| **grants** | One-off top-ups an administrator gives by hand |
| **used** | Read straight from `usagedaily`, which the meter already writes |

That last row is the design. There is **no second ledger** to keep in step and
no counter that can drift — the balance is a function of rows written for
another reason entirely. It is therefore impossible for the balance to disagree
with the usage page, because they are the same rows.

It is also cheap: every check is two aggregates over indexed columns, which is
what makes checking before *every* metered operation affordable. A limit
checked hourly is a limit somebody can drive straight through.

## The two tools, and which to use

| Want | Use | Where |
|---|---|---|
| This account/group gets more **every month** | the **allowance** | Admin → Groups, or the account's override |
| This account needs more **once** | a **grant** | Admin → Users → ⋯ → Credits |

A grant **expires**, defaulting to the end of the month it was given in. That is
not an arbitrary restriction: the allowance renews monthly and does not
accumulate, so a grant that never expired would behave differently from
everything around it, and working out how much of it had been spent would need
exactly the stored, driftable counter this design avoids.

## Where it is enforced

Checked at the *start* of an operation, before any model is called:

| Path | Where |
|---|---|
| Asking | `ask.py` — all three of `/ask/`, `/ask/stream`, `/ask/context` |
| Searching | `search.py` `/search/retrieve` |
| Uploading | `imports.py` (single, combined, batch, retry) and `data_sources.py` (Drive) |
| Translating | `documents.py` |
| Indexing | `worker/pipeline.py`, via `queue.has_credit` |

Not checked before every call *inside* an operation. An Ask that runs a few
hundred credits past zero on its last question is not worth re-checking
mid-flight; what matters is that the next one is refused, and it is.

Routes answer **402 Payment Required** — the one status that means exactly
this, and the interface reads it to show the balance rather than a generic
failure. The worker **fails** a job rather than retrying it: a balance does not
become untrue on a second attempt.

## Things to know

* **`GET /search/` is never refused.** Keyword search calls no model, so there
  is nothing to pay for. Running out stops you spending, not reading.
* **Administrators are not metered** out of their own installation, for the
  same reason they get a large page allowance.
* **Work belonging to nobody is never refused** — indexing a page whose author
  was deleted is not chargeable to anybody.
* **Cached tokens are charged like any other.** They are cheaper for us, not
  free, and a limit that moved with how well the provider's cache happened to
  be doing would be impossible to plan against.
* **Bookkeeping rows are not charged.** `usagedaily` rows with `kind='feature'`
  count what a person did rather than what was called to do it; charging them
  would bill the same work twice.
* **A credit is not a cost.** Users see credits and never money — that is the
  point of having a unit of our own. Cost stays on the admin usage tab.

### Adding a limit later

`monthly_credits` was added as the fourth entry in the `LIMITS` registry, and
it cost what `docs/LIMITS.md` promised: a nullable column on `user` and on
`usergroup`, one registry entry, and the admin schemas. The admin form drew
itself. One route had to be fixed to stop naming limits by hand — it now builds
from the registry too, so the next one really is four lines.
