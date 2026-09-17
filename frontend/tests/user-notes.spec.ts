/**
 * Personal notes, from the outside.
 *
 * Not `notes.spec.ts` - that one is the remarks people leave on a page, which
 * is a different feature that happens to share a word.
 */

import { expect, type Page, test } from "@playwright/test"

import { API, adminToken, uid } from "./utils/api.ts"

async function createNote(
  page: Page,
  body: Record<string, unknown>,
): Promise<{ id: string; title: string }> {
  const token = await adminToken(page.request)
  const made = await page.request.post(`${API}/notes/`, {
    headers: { Authorization: `Bearer ${token}` },
    data: body,
  })
  expect(made.ok(), await made.text()).toBeTruthy()
  return await made.json()
}

test("a note can be written from the board and opened", async ({ page }) => {
  const word = `aubergine${uid()}`
  await page.goto("/notes")
  await expect(page.getByTestId("notes-composer")).toBeVisible()

  await page.getByTestId("notes-composer-open").click()
  await page.getByTestId("notes-composer-title").fill(`Shopping ${word}`)
  await page.getByTestId("notes-composer-input").fill("Milk\nBread")
  await page.getByTestId("notes-composer-save").click()

  const card = page.getByTestId("notes-card").filter({ hasText: word })
  await expect(card).toBeVisible()

  // Saving keeps you on the board: a captured thought should not move you.
  await expect(page).toHaveURL(/\/notes\/?(\?.*)?$/)

  await card.getByRole("link").first().click()
  await expect(page.getByTestId("notes-editor")).toBeVisible()
  await expect(page.getByTestId("notes-title")).toHaveValue(new RegExp(word))
})

test("a note is findable the moment it is saved", async ({ page }) => {
  const word = `pomegranate${uid()}`
  await createNote(page, { title: "Rent", content: `<p>${word}</p>` })

  // No worker has run. Postgres writes the search vector at COMMIT.
  await page.goto(`/notes/search?q=${word}`)
  const results = page.getByTestId("notes-search-result")
  await expect(results).toHaveCount(1)
  await expect(results.first()).toContainText("Rent")
})

test("archiving takes a note off the board but not out of search", async ({
  page,
}) => {
  const word = `quince${uid()}`
  const note = await createNote(page, {
    title: `Old ${word}`,
    content: `<p>${word}</p>`,
  })

  await page.goto("/notes")
  const card = page.getByTestId("notes-card").filter({ hasText: word })
  await card.getByTestId("notes-card-menu").click()
  await page.getByTestId("notes-action-archive").click()
  await expect(card).toHaveCount(0)

  await page.goto("/notes?filter=archived")
  await expect(
    page.getByTestId("notes-card").filter({ hasText: word }),
  ).toBeVisible()

  await page.goto(`/notes/search?q=${word}`)
  await expect(page.getByTestId("notes-search-result")).toHaveCount(1)

  // And the note itself is read-only while it is away.
  await page.goto(`/notes/${note.id}`)
  await expect(page.getByTestId("notes-title")).toBeDisabled()
})

test("a checklist counts what is done", async ({ page }) => {
  const word = `basil${uid()}`
  await createNote(page, {
    kind: "checklist",
    title: `List ${word}`,
    content:
      '<ul data-type="taskList">' +
      '<li data-checked="true"><div><p>Milk</p></div></li>' +
      '<li data-checked="false"><div><p>Bread</p></div></li></ul>',
  })

  await page.goto("/notes")
  const card = page.getByTestId("notes-card").filter({ hasText: word })
  await expect(card).toContainText("1/2")
})

test("a note can be copied, and the copy is its own note", async ({ page }) => {
  const word = `cardamom${uid()}`
  await createNote(page, { title: `Recipe ${word}`, content: `<p>${word}</p>` })

  await page.goto("/notes")
  const card = page.getByTestId("notes-card").filter({ hasText: word })
  await card.getByTestId("notes-card-menu").click()
  await page.getByTestId("notes-action-clone").click()

  // Scoped to this run's own word: the board carries every earlier run's notes
  // too, and "(copy)" alone matches all of them.
  const mine = page.getByTestId("notes-card").filter({ hasText: word })
  await expect(mine).toHaveCount(2)
  await expect(mine.filter({ hasText: "(copy)" })).toHaveCount(1)
})
