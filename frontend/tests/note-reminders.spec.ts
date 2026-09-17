/**
 * A reminder, from setting it to reading the mail it sends.
 *
 * The mail is sent by the *worker*, not the API, and the two are separate
 * processes. Nothing had ever emailed from the worker before this feature, so
 * the dev mailbox could not see it at all until it was backed by a table -
 * which is the only reason this test can be written.
 */

import { expect, test } from "@playwright/test"

import { API, adminToken, uid } from "./utils/api.ts"
import { reminderEmail } from "./utils/mail.ts"

test("a reminder arrives, with the note in it", async ({ page, request }) => {
  const token = await adminToken(request)
  const word = `tarragon${uid()}`

  const made = await request.post(`${API}/notes/`, {
    headers: { Authorization: `Bearer ${token}` },
    data: { title: `Rent ${word}`, content: `<p>${word}</p>` },
  })
  expect(made.ok(), await made.text()).toBeTruthy()
  const note = await made.json()

  const me = await request.get(`${API}/users/me`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  const email = (await me.json()).email as string

  // A few seconds out: the worker polls every second, so this is a real wait
  // rather than a mocked clock.
  const zone = "Europe/Berlin"
  const soon = new Date(Date.now() + 5_000)
  const local = new Intl.DateTimeFormat("sv-SE", {
    timeZone: zone,
    dateStyle: "short",
    timeStyle: "medium",
  })
    .format(soon)
    .replace(" ", "T")

  const set = await request.put(`${API}/notes/${note.id}/reminder`, {
    headers: { Authorization: `Bearer ${token}` },
    data: { at: local, timezone: zone, recurrence: "none" },
  })
  expect(set.ok(), await set.text()).toBeTruthy()

  const mail = await reminderEmail(request, email, word)
  expect(mail.text).toContain(`/notes/${note.id}`)

  const after = await request.get(`${API}/notes/${note.id}/reminder`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  const state = await after.json()
  expect(state.status).toBe("done")
  expect(state.sent_count).toBe(1)

  // And the dialog opens on the note it belongs to.
  await page.goto("/notes")
  const card = page.getByTestId("notes-card").filter({ hasText: word })
  await card.getByTestId("notes-card-menu").click()
  await page.getByTestId("notes-action-remind").click()
  await expect(page.getByTestId("notes-reminder-dialog")).toBeVisible()
  await expect(page.getByTestId("notes-reminder-summary")).toContainText(
    "Emailed",
  )
})

test("a recurring reminder keeps its wall clock", async ({ request }) => {
  /**
   * Asserted on the local time rather than the instant: across a daylight
   * saving change the next occurrence is 23 or 25 hours later, and the whole
   * point is that the reading on the clock does not move.
   */
  const token = await adminToken(request)
  const made = await request.post(`${API}/notes/`, {
    headers: { Authorization: `Bearer ${token}` },
    data: { title: `Daily ${uid()}` },
  })
  const note = await made.json()

  const set = await request.put(`${API}/notes/${note.id}/reminder`, {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      at: "2026-12-01T09:00:00",
      timezone: "Europe/Berlin",
      recurrence: "daily",
    },
  })
  expect(set.ok(), await set.text()).toBeTruthy()
  const reminder = await set.json()

  expect(reminder.local_time).toBe("09:00:00")
  expect(reminder.recurrence).toBe("daily")
  expect(reminder.status).toBe("active")
})
