# Marketing: the one kind of mail nobody asked for

Everything else this application sends is transactional. Somebody confirms an
address, resets a password, or sets a reminder, and the message that follows is
the thing they just asked for. It goes to one person, it needs no unsubscribe
link, and nobody has to be persuaded to want it.

Bulk mail is a different thing with different obligations, and this is where it
lives: `/admin?tab=marketing`, superuser only.

## Three tables

| Table | Holds |
|---|---|
| `marketingcontact` | An address we may write to, and whether we still may |
| `marketingcampaign` | One message, and its running totals |
| `marketingdelivery` | One row per recipient per campaign, and what happened |

## A contact is not a `User`

This was the first idea and it does not survive contact with the code:

* `users.register_user` treats an existing **unverified** row as somebody
  registering a second time and only re-sends verification. A contact row has
  no password anybody knows, so every person on the list would have been locked
  out of ever creating an account by the act of being emailed.
* `login.reset_password` sets `email_verified_at`, so a cold contact could have
  promoted itself into a verified account.
* `admin_users.read_admin_users` selects every `User` with no filter, so the
  console, the account count and the per-row quota and credit arithmetic would
  all be computed over several hundred strangers.
* `User.hashed_password` is NOT NULL with no default, and there is nothing
  honest to put in it.

`ShareInvitation` had already established the shape for an address with no
account behind it, and this follows it, down to the nullable `user_id` for the
day the address becomes one.

**Signing up puts you on the list.** `crud.create_user` calls
`marketing.ensure_contact`, which is the single funnel for signup, admin-created
and seeded accounts. It never revives an unsubscribed contact, and it can never
fail a registration.

## One email per second, and no sleep anywhere

Each delivery is stamped `send_after = started_at + (index x 1 second)` when the
campaign is created. The worker claims only what is due, so exactly one row
becomes sendable per second and **the rate is a property of the data**.

That buys three things a sleeping loop does not:

* it survives a restart, and a half-sent campaign resumes where it stopped;
* `MARKETING_SEND_PER_TICK` caps the claim, so a worker returning from an
  outage sends at one a second rather than emptying an hour of backlog at once;
* the schedule is inspectable. "When does this one go out" is a column.

Sending is **at most once by construction**: the claim, the lease and the commit
happen before the message goes out, and `UniqueConstraint(campaign_id,
contact_id)` means two workers claiming the same row still produce one email. A
crash between the commit and the send loses a message rather than repeating one.
A duplicate marketing email is the one people remember, and it is charged
against the sending domain.

**Unsubscribing mid-campaign stops the rest.** At one a second a real list takes
about eleven minutes, which is long enough for somebody to read the first
message and leave before the last one is sent. The claim re-checks, and marks
the rest `skipped`, not `failed`.

## Who a campaign reaches

The ids the composer sends, minus anybody who unsubscribed in between. There is
no second rule and no widening flag, and there was one for about a day: a
checkbox that could broaden the audience after the count had been read is the
one thing a confirmation screen cannot protect anybody from. Sending to
everybody is what **Select all** on the contacts list is for, and it fills the
same field.

The count is stated twice before anything goes out: on the composer, as a
sentence rather than a number beside a button, and again in the confirmation,
along with the from address, the subject and how long the send will take. One a
second means the count is also the duration, and six hundred addresses is ten
minutes of sending.

## Editing a contact

`PATCH /admin/marketing/contacts/{id}` corrects a name or an address. It keeps
the unsubscribe token, because a link already sitting in somebody's inbox has to
keep working, and it keeps `unsubscribed_at`, because fixing a misspelling must
never be a way of putting somebody who left back on the list. A new address that
already belongs to another contact is a 409.

## The unsubscribe link, and the trap it avoids

Outlook Safe Links, Gmail's proxy and most corporate scanners fetch every URL in
a message before a human sees it. A `GET /unsubscribe/{token}` that acted would
therefore unsubscribe a large part of any list within minutes of the send, and
the first anybody would know is a campaign that reached nobody.

So the endpoint is `POST /api/v1/public/marketing/unsubscribe/{token}`, and the
page at `/unsubscribe/{token}` issues it from the browser. A scanner reads the
HTML, runs no JavaScript, and changes nothing. A person still only clicks once.

The token is plaintext and opaque, like `Document.public_slug` and unlike an
`AuthCode`: it must keep working for years, must survive being sent again in a
later campaign, and grants nothing except the right to stop being emailed.
Unsubscribing twice succeeds, because somebody with two of our messages open has
not made a mistake.

Marketing mail also carries `List-Unsubscribe` and
`List-Unsubscribe-Post: List-Unsubscribe=One-Click`, which is what puts the
unsubscribe control in Gmail's own interface. That needs headers `send_email`
cannot set, so campaigns go out through `send_raw_email`; every transactional
message is untouched.

## The default message

`marketing.DEFAULT_BODY_HTML` is seeded into the composer and is meant to be
rewritten; the next campaign will be a different message. Three things in it are
not style choices:

* **Inline styles on every element, and no stylesheet.** Mail clients strip
  `<style>` blocks, and half of them strip `class` attributes with it.
* **The logo is a PNG at an absolute URL.** Gmail and Outlook render no SVG and
  resolve no relative path.
* **The logo's `alt` is empty and the wordmark beside it is real text.** Most
  clients block images by default, so this way the header still reads as
  "PlusGPT" rather than as a broken-image box.

## What to call somebody

`{{name}}` is not the name column. A list imported from another product's
sign-up form contains `asdf`, `777`, `P`, `Test Guy`, somebody's email address
and three copies of a spam link, and "Hi asdf," is worse than no name at all.

`marketing.greeting_name` takes the first word and requires two to twenty
letters, rejects a known placeholder list, and rejects a vowel-less Latin word
(`PK`, `xp`, `Zh`). The letter test is Unicode-aware, so `Paweł`, `Александр`
and `Trần` are greeted properly; the vowel test is ASCII-only, because other
scripts write vowels differently. Anything else becomes `there`.

Against the real 662-row list, 605 people get their own name and everything that
falls through genuinely is junk.

The body is HTML the administrator wrote, so it goes in as markup. `{{name}}`
and `{{email}}` came from an uploaded file, so they are escaped first.

## Getting a list in

`POST /admin/marketing/contacts/import` takes a CSV upload. It accepts the
Cognito export's headers or a plain `name,email`, folds punctuation in column
headings so `Full Name` works, normalises addresses, and reports every row it
could not use rather than refusing the file over one bad address.

An upload rather than a script reading a checked-in file: several hundred real
addresses are not something a repository should carry. `/*.csv` is in
`.gitignore` for the same reason.

## Configuration

```
MARKETING_FROM_ADDRESSES   shanaka@plusgpt.io, noreply@plusgpt.io
MARKETING_SEND_PER_TICK    1
MARKETING_MAX_ATTEMPTS     3
MARKETING_MAX_RECIPIENTS   20000
```

**Every from-address has to be a verified SES identity.** An unverified sender
does not fail once, it fails every message in the campaign, one a second, for as
long as the campaign lasts. The deployed IAM user holds `ses:SendEmail` only, so
this cannot be checked from the server: check it in the console before the first
send.

## What this does not do yet

Bounces are not fed back. SES counts them against the account's reputation, and
a list with addresses that were never confirmed will produce some. For a one-off
invite that is an acceptable cost; before a second campaign to the same list,
the thing to add is an SNS bounce topic that marks a contact `hard_bounced` so
the next campaign skips it.
