/**
 * Sketching a note, and getting it back.
 *
 * The drawing surface is pointer events and an `<svg>`, so this drives it with
 * real pointer moves rather than stubbing anything: what is worth proving is
 * that a stroke becomes a path, that Save turns it into a stored picture, and
 * that reopening the note shows the same sketch.
 */

import { expect, type Page, test } from "@playwright/test"

import { API, adminToken, uid } from "./utils/api.ts"

/** One diagonal stroke across the canvas. */
async function draw(page: Page) {
  const surface = page.getByTestId("notes-drawing-surface")
  const box = await surface.boundingBox()
  if (!box) throw new Error("the drawing surface is not on screen")
  await page.mouse.move(box.x + box.width * 0.2, box.y + box.height * 0.3)
  await page.mouse.down()
  for (let step = 1; step <= 8; step += 1) {
    await page.mouse.move(
      box.x + box.width * (0.2 + 0.06 * step),
      box.y + box.height * (0.3 + 0.05 * step),
    )
  }
  await page.mouse.up()
}

test("a sketch is drawn, saved, and still there on the way back", async ({
  page,
}) => {
  const word = `sketch${uid()}`

  await page.goto("/notes")
  await page.getByTestId("notes-new-drawing").click()

  // A drawing opens straight into its own page: there is nothing to type.
  await expect(page.getByTestId("notes-drawing-surface")).toBeVisible()
  const url = page.url()

  await page.getByTestId("notes-title").fill(`Plan ${word}`)
  await draw(page)

  // The stroke is on the canvas, and Undo says so.
  await expect(
    page.locator('[data-testid="notes-drawing-surface"] path'),
  ).toHaveCount(1)
  await expect(page.getByTestId("notes-drawing-undo")).toBeEnabled()

  await page.getByTestId("notes-drawing-save").click()
  // The toast, not the button: the button is also disabled while the save is
  // still in flight, and the picture is uploaded after the strokes are.
  await expect(page.getByText("Drawing saved")).toBeVisible()

  await page.reload()
  await expect(
    page.locator('[data-testid="notes-drawing-surface"] path'),
  ).toHaveCount(1)
  expect(page.url()).toBe(url)

  // And the board shows the picture rather than an empty card.
  await page.goto("/notes")
  const card = page.getByTestId("notes-card").filter({ hasText: word })
  await expect(card.getByTestId("notes-card-drawing")).toBeVisible()
})

test("undo and clear take strokes back off", async ({ page }) => {
  await page.goto("/notes")
  await page.getByTestId("notes-new-drawing").click()
  await expect(page.getByTestId("notes-drawing-surface")).toBeVisible()

  await draw(page)
  await draw(page)
  const paths = page.locator('[data-testid="notes-drawing-surface"] path')
  await expect(paths).toHaveCount(2)

  await page.getByTestId("notes-drawing-undo").click()
  await expect(paths).toHaveCount(1)

  await page.getByTestId("notes-drawing-clear").click()
  await expect(paths).toHaveCount(0)
  await expect(page.getByTestId("notes-drawing-clear")).toBeDisabled()
})

test("a drawing's picture is stored under the note, not with attachments", async ({
  page,
  request,
}) => {
  /**
   * The whole reason drawings do not use the attachment routes: an attachment
   * with no document falls back to a namespace check, which would have handed
   * this to every member of the space.
   */
  await page.goto("/notes")
  await page.getByTestId("notes-new-drawing").click()
  await expect(page.getByTestId("notes-drawing-surface")).toBeVisible()
  await draw(page)
  await page.getByTestId("notes-drawing-save").click()
  // The toast, not the button: the button is also disabled while the save is
  // still in flight, and the picture is uploaded after the strokes are.
  await expect(page.getByText("Drawing saved")).toBeVisible()

  const noteId = page.url().split("/notes/")[1]
  const token = await adminToken(request)
  const listed = await request.get(`${API}/notes/${noteId}/assets`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  expect(listed.ok(), await listed.text()).toBeTruthy()
  const asset = (await listed.json()).data[0]
  expect(asset.content_type).toBe("image/png")
  expect(asset.download_url).toContain(`/notes/${noteId}/assets/`)

  // It is under the note, not under /attachments, so the only way to it runs
  // through the ownership check. `test_user_notes_privacy.py` is what proves
  // another account gets a 404; this proves the URL is the private shape.
  expect(asset.download_url).not.toContain("/attachments/")
})
