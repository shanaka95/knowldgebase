import fs from "node:fs"
import path from "node:path"
import type { APIRequestContext, APIResponse } from "@playwright/test"
import { expect } from "@playwright/test"
import { firstSuperuser, firstSuperuserPassword } from "../config.ts"
import { twoFactorCode } from "./mail.ts"

/** Absolute API base — tests call the backend directly for setup/assertions. */
export const API = `${process.env.VITE_API_URL ?? "http://localhost:8800"}/api/v1`

export const uid = () => Math.random().toString(36).slice(2, 8)

export const auth = (token: string) => ({ Authorization: `Bearer ${token}` })

/**
 * Sign in the way the product does: the password buys a challenge, the code
 * emailed to the address buys the session. There is no shortcut, by design.
 */
export async function getToken(
  request: APIRequestContext,
  email: string,
  password: string,
): Promise<string> {
  const challenge = await request.post(`${API}/login/access-token`, {
    form: { username: email, password },
  })
  expect(challenge.ok(), await challenge.text()).toBeTruthy()
  const { challenge_token } = await challenge.json()

  const code = await twoFactorCode(request, email)
  const session = await request.post(`${API}/login/two-factor`, {
    data: { challenge_token, code },
  })
  expect(session.ok(), await session.text()).toBeTruthy()
  return (await session.json()).access_token as string
}

const AUTH_FILE = path.join(process.cwd(), "playwright/.auth/user.json")

/**
 * The superuser's session, borrowed from the storage state the `setup` project
 * saved. Signing in again for every test would email a sign-in code every time
 * and walk straight into the backend's send limit, so the suite would end up
 * testing the rate limiter rather than the feature under test.
 */
export async function adminToken(request?: APIRequestContext): Promise<string> {
  if (fs.existsSync(AUTH_FILE)) {
    const state = JSON.parse(fs.readFileSync(AUTH_FILE, "utf8"))
    for (const origin of state.origins ?? []) {
      for (const item of origin.localStorage ?? []) {
        if (item.name === "access_token" && item.value) return item.value
      }
    }
  }
  if (!request) {
    throw new Error(`no saved session in ${AUTH_FILE} and no request context`)
  }
  return getToken(request, firstSuperuser, firstSuperuserPassword)
}

async function expectOk(r: APIResponse) {
  if (!r.ok()) {
    throw new Error(`${r.status()} ${r.url()}\n${await r.text()}`)
  }
  return r.json()
}

/** Create a regular user through the dev-only private endpoint. */
export async function createTestUser(
  request: APIRequestContext,
  overrides: {
    email?: string
    password?: string
    full_name?: string
    is_verified?: boolean
  } = {},
) {
  const email = overrides.email ?? `e2e_${uid()}@example.com`
  const password = overrides.password ?? `pw_${uid()}${uid()}`
  const r = await request.post(`${API}/private/users/`, {
    data: {
      email,
      password,
      full_name: overrides.full_name ?? "E2E User",
      // An account with an unconfirmed address cannot sign in at all, and a
      // fixture has no inbox to confirm from.
      is_verified: overrides.is_verified ?? true,
    },
  })
  const user = await expectOk(r)
  return { email, password, id: user.id as string, full_name: user.full_name }
}

export async function createNamespace(
  request: APIRequestContext,
  token: string,
  body: Partial<{
    name: string
    description: string
    icon: string
    color: string
  }> = {},
) {
  const r = await request.post(`${API}/namespaces/`, {
    headers: auth(token),
    data: { name: `Space ${uid()}`, ...body },
  })
  return expectOk(r)
}

export async function createFolder(
  request: APIRequestContext,
  token: string,
  namespaceId: string,
  name = `Folder ${uid()}`,
  parentId: string | null = null,
) {
  const r = await request.post(`${API}/folders/`, {
    headers: auth(token),
    data: { namespace_id: namespaceId, name, parent_id: parentId },
  })
  return expectOk(r)
}

export async function createDocument(
  request: APIRequestContext,
  token: string,
  namespaceId: string,
  body: Partial<{
    title: string
    content: string
    content_format: "html" | "markdown" | "text"
    folder_id: string | null
    doc_type: string
  }> = {},
) {
  const r = await request.post(`${API}/documents/`, {
    headers: auth(token),
    data: {
      namespace_id: namespaceId,
      title: `Page ${uid()}`,
      content: "<p>Hello from e2e</p>",
      content_format: "html",
      ...body,
    },
  })
  return expectOk(r)
}

export async function getDocument(
  request: APIRequestContext,
  token: string,
  id: string,
) {
  return expectOk(
    await request.get(`${API}/documents/${id}`, { headers: auth(token) }),
  )
}

export async function updateDocument(
  request: APIRequestContext,
  token: string,
  id: string,
  body: Record<string, unknown>,
) {
  return request.put(`${API}/documents/${id}`, {
    headers: auth(token),
    data: body,
  })
}

export async function getEmbeddings(
  request: APIRequestContext,
  token: string,
  id: string,
) {
  return expectOk(
    await request.get(`${API}/documents/${id}/embeddings`, {
      headers: auth(token),
    }),
  )
}

/**
 * Wait until the embedding worker has indexed a page. Chunking and summarising
 * call a local LLM, so this is minutes, not seconds; a transient connection
 * error (a container restart mid-run) is retried rather than failing the test.
 */
export async function waitForIndexed(
  request: APIRequestContext,
  token: string,
  documentId: string,
  timeout = 300_000,
): Promise<void> {
  const deadline = Date.now() + timeout
  let last = "unknown"
  while (Date.now() < deadline) {
    try {
      const r = await request.get(`${API}/documents/${documentId}/embeddings`, {
        headers: auth(token),
      })
      if (r.ok()) {
        last = (await r.json()).embedding_status
        if (last === "ready") return
        if (last === "failed")
          throw new Error(`indexing failed for ${documentId}`)
      }
    } catch (err) {
      if (err instanceof Error && err.message.includes("indexing failed"))
        throw err
      // the API briefly went away — keep waiting
    }
    await new Promise((resolve) => setTimeout(resolve, 4_000))
  }
  throw new Error(
    `document ${documentId} was not indexed within ${timeout}ms (last status: ${last})`,
  )
}

export async function shareDocument(
  request: APIRequestContext,
  token: string,
  documentId: string,
  email: string,
  role: "viewer" | "editor",
) {
  return request.post(`${API}/documents/${documentId}/shares`, {
    headers: auth(token),
    data: { email, role },
  })
}

export async function shareDocumentWithMany(
  request: APIRequestContext,
  token: string,
  documentId: string,
  body: { emails: string[]; role?: "viewer" | "editor"; message?: string },
) {
  return request.post(`${API}/documents/${documentId}/shares/batch`, {
    headers: auth(token),
    data: { role: "viewer", ...body },
  })
}

export async function getInvitations(
  request: APIRequestContext,
  token: string,
  documentId: string,
) {
  return expectOk(
    await request.get(`${API}/documents/${documentId}/invitations`, {
      headers: auth(token),
    }),
  )
}

export async function publishDocument(
  request: APIRequestContext,
  token: string,
  documentId: string,
) {
  return expectOk(
    await request.post(`${API}/documents/${documentId}/public`, {
      headers: auth(token),
    }),
  )
}

export async function addMember(
  request: APIRequestContext,
  token: string,
  namespaceId: string,
  email: string,
  role: "viewer" | "editor" | "admin",
) {
  return request.post(`${API}/namespaces/${namespaceId}/members`, {
    headers: auth(token),
    data: { email, role },
  })
}

export async function createApiKey(
  request: APIRequestContext,
  token: string,
  body: { name?: string; scope: "read" | "write"; expires_in_days?: number },
) {
  return expectOk(
    await request.post(`${API}/api-keys/`, {
      headers: auth(token),
      data: { name: body.name ?? `key ${uid()}`, ...body },
    }),
  )
}

/** A 1×1 transparent PNG, enough for upload round-trips. */
export const TINY_PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==",
  "base64",
)

/** Multi-topic markdown that the LLM should split into several chunks. */
export const MULTI_TOPIC_MARKDOWN = `# Team notes

## Quarterly budget review
Finance presented the Q3 numbers on Tuesday. Cloud spend is 18% over plan, mostly from the new GPU nodes used for the recommendation experiments. We agreed to right-size the staging cluster and to move nightly batch jobs to spot instances. Each team lead must submit a revised forecast by the 20th so the CFO can present a consolidated view to the board.

## Kitchen and office etiquette
Several complaints came in about dishes left in the sink and food abandoned in the fridge over the weekend. From now on, the fridge is cleaned every Friday at 17:00 and anything unlabeled is thrown away. Please label containers with your name and date. The coffee machine is descaled on Monday mornings, so expect it to be unavailable until 9:30.

## Python 3.14 migration
The platform team finished migrating the ingestion services to Python 3.14. The main change is the new template-string syntax and the removal of several deprecated asyncio APIs; two libraries needed upgrades. CI now runs on 3.14 only. Remaining services must migrate before the end of the quarter; a checklist and a compatibility matrix are in the engineering wiki.
`

export async function shareNamespaceWithMany(
  request: APIRequestContext,
  token: string,
  namespaceId: string,
  body: {
    emails: string[]
    role?: "viewer" | "editor" | "admin"
    message?: string
  },
) {
  return request.post(`${API}/namespaces/${namespaceId}/members/batch`, {
    headers: auth(token),
    data: { role: "viewer", ...body },
  })
}

export async function getMembers(
  request: APIRequestContext,
  token: string,
  namespaceId: string,
) {
  return expectOk(
    await request.get(`${API}/namespaces/${namespaceId}/members`, {
      headers: auth(token),
    }),
  )
}

export async function getNamespaceInvitations(
  request: APIRequestContext,
  token: string,
  namespaceId: string,
) {
  return expectOk(
    await request.get(`${API}/namespaces/${namespaceId}/invitations`, {
      headers: auth(token),
    }),
  )
}
