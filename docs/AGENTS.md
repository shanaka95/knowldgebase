# Hosted agents

An **agent** is the knowledge base with a chat window in front of it. A user
creates one in the dashboard, connects a messaging channel to it, and can then
ask it what their tenancy agreement says, or send it a photo of a receipt to
file, without opening PlusGPT.

Agents run on [Hermes Agent](https://github.com/shanaka95/hermes-agent), hosted
by us. This document covers the tenancy model, the linking protocol, and the
things that would be dangerous to change without knowing why they are the way
they are.

---

## The tenancy model

**One agent is one Hermes profile.** A profile is a directory — `config.yaml`,
`.env`, `SOUL.md`, and the SQLite conversation store beside them — and it is the
unit Hermes actually isolates: its own secrets, its own memory, its own MCP
connection. Mapping "agent" onto "profile" means the product's idea of an agent
and the framework's idea of a tenant are the same thing.

```
/hermes-profiles/
  shard-0/
    config.yaml          the shared bots, and where to ask who a sender is
    .env                 platform credentials for those bots
    profiles/
      a-1f3c9e0b…/       one agent
        config.yaml      the MCP server, referenced as ${PLUSGPT_API_KEY}
        .env             that agent's key and model token — nothing else
        SOUL.md          its name and persona
        state.db         its conversations
```

The backend writes these directories; the shards read them. Provisioning is a
filesystem write and nothing more, because `profiles_to_serve()` in Hermes is a
live directory read performed on every inbound message — a new agent works
without restarting anything.

**Shards** exist to bound the damage from any in-process isolation failure, and
to keep one gateway's turn pool (`ThreadPoolExecutor(max_workers=10)`) from
becoming everybody's queue. An agent is pinned to a shard at creation, because
its profile lives on that shard's volume. Profiles are rebuildable from the
database at any time, so a lost shard is re-provisioned rather than restored.

---

## How a message finds its agent

Everyone messages the same bot. A phone number arriving at it is a claim, not a
credential — anyone can message our number.

```
message → shard → POST /api/v1/agent-control/route
                     {"platform": "telegram", "chat_id": "…", "message_text": "…"}
                  ← {"profile": "a-1f3c…"}   run the turn in that profile
                  ← {"profile": null}         drop the message, say nothing
```

Three rules, each of which exists because the alternative leaks:

- **Unknown means dropped, never defaulted.** Returning "the default profile"
  for an unrecognised sender would put a stranger's message into whichever agent
  happens to be default. `gateway/profile_route_provider.py` raises
  `ProfileRouteRejected` instead, and the gateway drops the event.
- **A failed lookup is also dropped.** If the control plane is unreachable we do
  not know who this is, and guessing routes someone's message to the wrong
  agent. Refusing is the only safe answer.
- **Nothing the message says affects routing.** The text is searched for a link
  code and otherwise ignored. A caller naming a profile in the payload is
  ignored too — there is a test that fails if that stops being true.

Answers are cached briefly in the shard, both ways: a shared number attracts
strangers, and each of their messages would otherwise cost a round trip. A
message carrying text always reaches the control plane anyway, because it might
*become* a link.

### Why unlinked senders get silence

Not an oversight. Replying would confirm the number is live, invite abuse of a
metered API, and — if the reply were generated — hand an unauthenticated party a
language model. The dashboard tells the user what to do; the bot does not talk
to strangers.

---

## Linking a channel

1. The user picks a channel on their agent's page. The backend issues a
   one-time code — `LINK-7QK2-9F3N` — and returns the plaintext once.
2. They send it from the channel.
3. The route lookup finds no connection, spots the code in the text, redeems it,
   and answers with the profile it has just bound. The same message then runs as
   a normal turn, so the agent's first reply is a real one.
4. The dashboard is polling, and the connection appears.

The code is stored SHA-256-hashed, single-use, and expires in fifteen minutes,
because the plaintext travels through a messaging app and may sit in a chat log
forever. Its alphabet excludes `O`, `0`, `I`, `1` and `L`, so a mistyped code
fails rather than binding the wrong account.

`(channel_type, platform_identity)` is unique in the database. That is the
product rule — one channel account connects once — enforced where a race cannot
get past it, and it is also what stops a second code relinking an account
somebody already holds.

---

## What keeps one user's data away from another's

Layered, because Hermes' own `SECURITY.md` is blunt that in-process controls are
not a boundary: *"the only security boundary against an adversarial LLM is the
operating system… not any tool allowlist."*

| Layer | What it stops |
|---|---|
| Per-profile `.env` and Hermes' fail-closed secret scope | An agent resolving another agent's knowledge-base key. An unscoped read raises rather than falling back to the process environment. |
| `enabled_toolsets: [skills, todo, vision]` | Shell, filesystem and browser access. There is nothing for an injected prompt to drive. |
| Outbound media confined to the profile (fork patch) | Exfiltration by `MEDIA:<path>`. This is *not* covered by the toolset restriction: MCP tool results legitimately put real paths in the model's context, and a model can rewrite one into a sibling's path. |
| The LLM proxy | The provider key landing on a shard at all. Agents hold a per-agent token for `/api/v1/agent-llm`; the real key stays on the backend, and usage is attributable. |
| Sharding | The blast radius of anything that does get through. |
| The knowledge base itself | Everything else. The MCP server answers to a key scoped to one user, so what an agent *says* about who it is changes nothing. |

Identity is decided by code at every step — the transport's identity, a
cryptographic one-time secret, and an API key — never by the agent's own
assertion. `backend/tests/api/routes/test_agents.py` has a section pinning
exactly that.

---

## Configuring a channel

Admins go to **Admin → Channels**. A channel is offered to users only when it is
both configured and enabled. Credentials are encrypted with `CHANNEL_SECRET_KEY`
and never returned by the API — only reported as set — so a compromised admin
session cannot read the platform tokens back.

Saving rewrites each shard's `config.yaml` and `.env` from the current settings,
so enabling a channel in the dashboard is the whole of enabling it.

### WhatsApp has two backends

- **Cloud API** — Meta's official Business API. Webhook ingress, priced per
  conversation, scales, and nobody can take it away from you. The right choice
  for production.
- **Local bridge** — signs in as an ordinary WhatsApp account over WhatsApp Web,
  free and instant, and against WhatsApp's terms. A ban takes every user's agent
  down at once. Fine for testing.

The choice is surfaced where it is made, with that trade-off written next to it.

---

## Environment

| Variable | Meaning |
|---|---|
| `HERMES_PROFILES_ROOT` | Where profiles are written. Must be the same volume the shards mount. |
| `HERMES_SHARD_COUNT` | How many gateway containers are running. Agents are spread across them deterministically. |
| `AGENT_CONTROL_TOKEN` | Shared secret a shard presents to the control plane. **Unset means every lookup is refused**, not that it is open. |
| `CHANNEL_SECRET_KEY` | Fernet key for admin channel credentials. Rotating it makes stored credentials unreadable; channels then read as unconfigured until re-entered. |
| `AGENT_LLM_MODEL` | The one model agents may use. Pinned server-side so an injected prompt cannot pick a more expensive one. |
| `HERMES_MCP_URL` | In-network address of the MCP server. |

---

## Changes to Hermes

Our fork carries three, all in `gateway/`, all worth upstreaming:

1. **Outbound media confinement** (`platforms/base.py`) — gated on
   `multiplex_profiles`, so single-tenant installs are untouched.
2. **HTTP route provider** (`profile_route_provider.py`) — additive; the static
   `profile_routes` list remains the default.
3. **Link-probe text on inbound** (`run_inbound.py`) — lets a first message
   carrying a code bind the sender.

Plus `docker/plusgpt-gateway.Dockerfile`: a lean image with no Node, Playwright
or source build of SQLite, since a hosted agent can use none of them.

---

## Operating notes

- A shard waits for its `config.yaml` before starting. A shard stuck in that
  wait means no channel has been enabled yet.
- Deleting an agent revokes its knowledge-base key *before* removing the
  directory, so a half-failed delete leaves an inert directory rather than a
  live key.
- Disconnecting a channel takes effect within the shard's negative-cache TTL
  (15 seconds), not instantly.
