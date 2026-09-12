import { expect, test } from "@playwright/test"
import {
  API,
  adminToken,
  auth,
  createDocument,
  createFolder,
  createNamespace,
  createTestUser,
  getDocument,
  getEmbeddings,
  shareDocument,
  TINY_PNG,
  uid,
  updateDocument,
} from "./utils/api.ts"

/**
 * API-level checks that mirror what the UI relies on. They run through the
 * Playwright request fixture against the live backend.
 */
test.describe("Document API consistency", () => {
  test("markdown create → sanitised HTML + plain text, version 1, pending index", async ({
    request,
  }) => {
    const token = await adminToken(request)
    const ns = await createNamespace(request, token)
    const doc = await createDocument(request, token, ns.id, {
      title: "Markdown page",
      content:
        "# Heading\n\nSome *emphasis* and <script>alert(1)</script> text.",
      content_format: "markdown",
    })
    expect(doc.content_html).toContain("<h1>Heading</h1>")
    expect(doc.content_html).toContain("<em>emphasis</em>")
    expect(doc.content_html).not.toContain("<script")
    expect(doc.content_text).toContain("Heading")
    expect(doc.content_text).toContain("Some emphasis and")
    expect(doc.content_text).not.toContain("<")
    expect(doc.version).toBe(1)
    expect(doc.embedding_status).toBe("pending")
    expect(doc.is_stale).toBe(true)
    expect(doc.namespace_slug).toBe(ns.slug)
    expect(doc.my_role).toBe("editor")
  })

  test("plain text create keeps paragraphs and escapes markup", async ({
    request,
  }) => {
    const token = await adminToken(request)
    const ns = await createNamespace(request, token)
    const doc = await createDocument(request, token, ns.id, {
      content: "line one\nline two\n\nsecond <b>para</b>",
      content_format: "text",
    })
    expect(doc.content_html).toBe(
      "<p>line one<br>line two</p><p>second &lt;b&gt;para&lt;/b&gt;</p>",
    )
    expect(doc.content_text).toBe("line one line two\n\nsecond <b>para</b>")
  })

  test("formatting-only edits do not bump the version; text edits do", async ({
    request,
  }) => {
    const token = await adminToken(request)
    const ns = await createNamespace(request, token)
    const doc = await createDocument(request, token, ns.id, {
      content: "<p>Stable text</p>",
    })
    // bold the same words
    let r = await updateDocument(request, token, doc.id, {
      content: "<p><strong>Stable</strong> text</p>",
      content_format: "html",
    })
    expect(r.ok()).toBeTruthy()
    let fresh = await r.json()
    expect(fresh.version).toBe(1)
    expect(fresh.content_html).toContain("<strong>Stable</strong>")

    // change the words
    r = await updateDocument(request, token, doc.id, {
      content: "<p>Changed text</p>",
      content_format: "html",
    })
    fresh = await r.json()
    expect(fresh.version).toBe(2)
    expect(fresh.embedding_status).toBe("pending")
    expect(fresh.is_stale).toBe(true)

    // title change also bumps
    r = await updateDocument(request, token, doc.id, { title: "New title" })
    fresh = await r.json()
    expect(fresh.version).toBe(3)
  })

  test("expected_version mismatch returns 409 with the current version", async ({
    request,
  }) => {
    const token = await adminToken(request)
    const ns = await createNamespace(request, token)
    const doc = await createDocument(request, token, ns.id)
    const r = await updateDocument(request, token, doc.id, {
      title: "stale write",
      expected_version: 99,
    })
    expect(r.status()).toBe(409)
    const body = await r.json()
    expect(body.detail.current_version).toBe(1)
    expect(body.detail.message).toMatch(/modified elsewhere/)
    // matching version succeeds
    const ok = await updateDocument(request, token, doc.id, {
      title: "fresh write",
      expected_version: 1,
    })
    expect(ok.ok()).toBeTruthy()
    expect((await ok.json()).version).toBe(2)
  })

  test("recent, search, tree and embeddings endpoints agree on a new page", async ({
    request,
  }) => {
    const token = await adminToken(request)
    const ns = await createNamespace(request, token)
    const folder = await createFolder(request, token, ns.id)
    const marker = `zebra${uid()}`
    const doc = await createDocument(request, token, ns.id, {
      title: `Consistency ${uid()}`,
      content: `<p>The word ${marker} only appears here.</p>`,
      folder_id: folder.id,
    })

    const recent = await (
      await request.get(`${API}/documents/recent`, { headers: auth(token) })
    ).json()
    expect(recent.data.map((d: { id: string }) => d.id)).toContain(doc.id)

    const search = await (
      await request.get(`${API}/search/?q=${marker}`, {
        headers: auth(token),
      })
    ).json()
    expect(search.count).toBe(1)
    expect(search.data[0].document_id).toBe(doc.id)
    expect(search.data[0].snippet).toContain("<mark>")
    expect(search.data[0].namespace_slug).toBe(ns.slug)

    const tree = await (
      await request.get(`${API}/namespaces/${ns.id}/tree`, {
        headers: auth(token),
      })
    ).json()
    expect(tree.folders.map((f: { id: string }) => f.id)).toContain(folder.id)
    const inTree = tree.documents.find((d: { id: string }) => d.id === doc.id)
    expect(inTree.folder_id).toBe(folder.id)
    expect(inTree.namespace_slug).toBe(ns.slug)

    const emb = await getEmbeddings(request, token, doc.id)
    expect(emb.version).toBe(1)
    expect(emb.kinds).toEqual(["document", "summary", "chunk"])
    expect([
      "pending",
      "chunking",
      "summarizing",
      "embedding",
      "ready",
    ]).toContain(emb.embedding_status)
    expect(emb.jobs.length).toBeGreaterThanOrEqual(1)

    const empty = await request.get(`${API}/search/?q=`, {
      headers: auth(token),
    })
    expect(empty.status()).toBe(422)
  })

  test("shares: add, list, update, remove; namespace members cannot be re-shared", async ({
    request,
  }) => {
    const token = await adminToken(request)
    const ns = await createNamespace(request, token)
    const doc = await createDocument(request, token, ns.id)
    const guest = await createTestUser(request)

    let r = await shareDocument(request, token, doc.id, guest.email, "viewer")
    expect(r.ok()).toBeTruthy()
    r = await shareDocument(request, token, doc.id, guest.email, "viewer")
    expect(r.status()).toBe(409)
    r = await shareDocument(
      request,
      token,
      doc.id,
      "nobody@example.com",
      "viewer",
    )
    expect(r.status()).toBe(404)

    const list = await (
      await request.get(`${API}/documents/${doc.id}/shares`, {
        headers: auth(token),
      })
    ).json()
    expect(list.count).toBe(1)
    expect(list.data[0].user.email).toBe(guest.email)

    r = await request.patch(`${API}/documents/${doc.id}/shares/${guest.id}`, {
      headers: auth(token),
      data: { role: "editor" },
    })
    expect((await r.json()).role).toBe("editor")

    r = await request.delete(`${API}/documents/${doc.id}/shares/${guest.id}`, {
      headers: auth(token),
    })
    expect(r.ok()).toBeTruthy()

    // a namespace member already has access → sharing is rejected
    const member = await createTestUser(request)
    await request.post(`${API}/namespaces/${ns.id}/members`, {
      headers: auth(token),
      data: { email: member.email, role: "viewer" },
    })
    r = await shareDocument(request, token, doc.id, member.email, "viewer")
    expect(r.status()).toBe(409)
  })

  test("folder moves reject cycles and cross-namespace parents", async ({
    request,
  }) => {
    const token = await adminToken(request)
    const ns = await createNamespace(request, token)
    const other = await createNamespace(request, token)
    const parent = await createFolder(request, token, ns.id, "parent")
    const child = await createFolder(request, token, ns.id, "child", parent.id)
    const foreign = await createFolder(request, token, other.id, "foreign")

    let r = await request.patch(`${API}/folders/${parent.id}`, {
      headers: auth(token),
      data: { parent_id: child.id },
    })
    expect(r.status()).toBe(400)
    r = await request.patch(`${API}/folders/${parent.id}`, {
      headers: auth(token),
      data: { parent_id: parent.id },
    })
    expect(r.status()).toBe(400)
    r = await request.patch(`${API}/folders/${child.id}`, {
      headers: auth(token),
      data: { parent_id: foreign.id },
    })
    expect([400, 404]).toContain(r.status())
    // valid: move child to root
    r = await request.patch(`${API}/folders/${child.id}`, {
      headers: auth(token),
      data: { move_to_root: true },
    })
    expect((await r.json()).parent_id).toBeNull()
  })

  test("attachment upload / download round-trip and auth", async ({
    request,
  }) => {
    const token = await adminToken(request)
    const ns = await createNamespace(request, token)
    const doc = await createDocument(request, token, ns.id)
    const r = await request.post(`${API}/attachments/`, {
      headers: auth(token),
      multipart: {
        namespace_id: ns.id,
        document_id: doc.id,
        file: { name: "dot.png", mimeType: "image/png", buffer: TINY_PNG },
      },
    })
    expect(r.ok(), await r.text()).toBeTruthy()
    const att = await r.json()
    expect(att.download_url).toBe(`/api/v1/attachments/${att.id}/download`)
    expect(att.size).toBe(TINY_PNG.length)
    expect(att.content_type).toBe("image/png")

    const dl = await request.get(`${API}/attachments/${att.id}/download`, {
      headers: auth(token),
    })
    expect(dl.ok()).toBeTruthy()
    expect(dl.headers()["content-type"]).toContain("image/png")
    expect(Buffer.from(await dl.body()).equals(TINY_PNG)).toBeTruthy()

    const anon = await request.get(`${API}/attachments/${att.id}/download`)
    expect(anon.status()).toBe(401)

    const stranger = await createTestUser(request)
    const strangerToken = await (
      await request.post(`${API}/login/access-token`, {
        form: { username: stranger.email, password: stranger.password },
      })
    ).json()
    const forbidden = await request.get(
      `${API}/attachments/${att.id}/download`,
      { headers: auth(strangerToken.access_token) },
    )
    expect(forbidden.status()).toBe(404)

    const list = await (
      await request.get(`${API}/attachments/?document_id=${doc.id}`, {
        headers: auth(token),
      })
    ).json()
    expect(list.count).toBe(1)

    const del = await request.delete(`${API}/attachments/${att.id}`, {
      headers: auth(token),
    })
    expect(del.ok()).toBeTruthy()
    expect(
      (
        await request.get(`${API}/attachments/${att.id}`, {
          headers: auth(token),
        })
      ).status(),
    ).toBe(404)
  })

  test("deleting a page removes it from tree, recent and search", async ({
    request,
  }) => {
    const token = await adminToken(request)
    const ns = await createNamespace(request, token)
    const marker = `kiwi${uid()}`
    const doc = await createDocument(request, token, ns.id, {
      content: `<p>${marker}</p>`,
    })
    const del = await request.delete(`${API}/documents/${doc.id}`, {
      headers: auth(token),
    })
    expect(del.ok()).toBeTruthy()
    expect(
      await getDocument(request, token, doc.id).catch(() => null),
    ).toBeNull()
    const tree = await (
      await request.get(`${API}/namespaces/${ns.id}/tree`, {
        headers: auth(token),
      })
    ).json()
    expect(tree.documents).toHaveLength(0)
    const search = await (
      await request.get(`${API}/search/?q=${marker}`, { headers: auth(token) })
    ).json()
    expect(search.count).toBe(0)
  })

  test("namespace metadata counts pages and members", async ({ request }) => {
    const token = await adminToken(request)
    const ns = await createNamespace(request, token)
    await createDocument(request, token, ns.id)
    await createDocument(request, token, ns.id)
    const member = await createTestUser(request)
    await request.post(`${API}/namespaces/${ns.id}/members`, {
      headers: auth(token),
      data: { email: member.email, role: "editor" },
    })
    const fresh = await (
      await request.get(`${API}/namespaces/by-slug/${ns.slug}`, {
        headers: auth(token),
      })
    ).json()
    expect(fresh.document_count).toBe(2)
    expect(fresh.member_count).toBeGreaterThanOrEqual(1)
    expect(fresh.my_role).toBe("admin")
    const members = await (
      await request.get(`${API}/namespaces/${ns.id}/members`, {
        headers: auth(token),
      })
    ).json()
    const owner = members.data.find((m: { is_owner: boolean }) => m.is_owner)
    expect(owner.role).toBe("admin")
    expect(
      members.data.find(
        (m: { user: { email: string } }) => m.user.email === member.email,
      ).role,
    ).toBe("editor")
  })
})
