import { expect, test } from "@playwright/test"

import {
  API,
  adminToken,
  auth,
  createDocument,
  createNamespace,
  uid,
} from "./utils/api.ts"

/**
 * Notes on a page, from the side that matters: they show up, they can be
 * written by hand, and they can be found by searching for what they say.
 */

test.setTimeout(120_000)

test.describe("Notes on a page", () => {
  test("a note can be added from the page and is shown there", async ({
    page,
    request,
  }) => {
    const token = await adminToken(request)
    const ns = await createNamespace(request, token, { name: `Notes ${uid()}` })
    const doc = await createDocument(request, token, ns.id, {
      title: `Invoice ${uid()}`,
      content: "<p>An invoice.</p>",
    })

    await page.goto(`/s/${ns.slug}/d/${doc.id}?mode=view`)
    const notes = page.getByTestId("document-notes")
    await expect(notes).toBeVisible()
    // The empty state is the invitation, in the words that were asked for.
    await expect(notes.getByTestId("add-note")).toContainText(
      "Anything you want to add to this document",
    )

    await notes.getByTestId("add-note").click()
    await notes
      .getByTestId("note-input")
      .fill("Paid in March; this is the disputed copy.")
    await notes.getByTestId("save-new-note").click()

    await expect(notes.getByTestId("note")).toHaveCount(1)
    await expect(notes.getByTestId("note")).toContainText("Paid in March")
    await expect(notes.getByTestId("note-count")).toHaveText("1")
  })

  test("a note can be edited and removed by the person who wrote it", async ({
    page,
    request,
  }) => {
    const token = await adminToken(request)
    const ns = await createNamespace(request, token, { name: `Notes ${uid()}` })
    const doc = await createDocument(request, token, ns.id, {
      title: `Contract ${uid()}`,
      content: "<p>A contract.</p>",
    })
    const created = await request.post(`${API}/documents/${doc.id}/notes/`, {
      headers: auth(token),
      data: { body: "First version of the note" },
    })
    expect(created.ok(), await created.text()).toBeTruthy()

    await page.goto(`/s/${ns.slug}/d/${doc.id}?mode=view`)
    const note = page.getByTestId("note").first()
    await expect(note).toBeVisible()

    await note.getByTestId("edit-note").click()
    await note.getByTestId("note-edit-input").fill("Corrected note")
    await note.getByTestId("save-note").click()
    await expect(page.getByTestId("note").first()).toContainText(
      "Corrected note",
    )

    await page.getByTestId("note").first().getByTestId("delete-note").click()
    await expect(page.getByTestId("note")).toHaveCount(0)
  })

  test("a note is findable by searching for what it says", async ({
    request,
  }) => {
    // The claim the whole design rests on. Through the API, because what is
    // being checked is the index rather than the interface.
    const token = await adminToken(request)
    const ns = await createNamespace(request, token, { name: `Notes ${uid()}` })
    const doc = await createDocument(request, token, ns.id, {
      title: `Policy ${uid()}`,
      content: "<p>Nothing in the body mentions it.</p>",
    })
    const sentinel = `zarquon${uid()}`
    await request.post(`${API}/documents/${doc.id}/notes/`, {
      headers: auth(token),
      data: { body: `Superseded — see ${sentinel} for the replacement.` },
    })

    const found = await request.get(`${API}/search/?q=${sentinel}`, {
      headers: auth(token),
    })
    expect(found.ok(), await found.text()).toBeTruthy()
    const ids = (await found.json()).data.map(
      (hit: { document_id: string }) => hit.document_id,
    )
    expect(ids).toContain(doc.id)
  })

  test("the upload dialog asks for a note", async ({ page }) => {
    await page.goto("/capture")
    await page.getByTestId("import-new").click()
    const field = page.getByTestId("import-note")
    await expect(field).toBeVisible()
    await expect(field).toHaveAttribute("placeholder", /what it replaces/)
  })
})
