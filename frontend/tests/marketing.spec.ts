/**
 * A campaign, from an uploaded list to the message in the mailbox.
 *
 * The send happens in the *worker*, a second at a time, and lands in the
 * development mailbox through `CapturedEmailRow` - which stores only the plain
 * text part, so everything asserted here has to be true of that part.
 */

import { expect, test } from "@playwright/test"

import { API, adminToken, uid } from "./utils/api.ts"
import { marketingEmail } from "./utils/mail.ts"

test("a list is uploaded, a message is sent, and it can be unsubscribed from", async ({
  page,
  request,
}) => {
  const word = `rosemary${uid()}`
  const address = `${word}@example.com`
  const token = await adminToken(request)
  const auth = { Authorization: `Bearer ${token}` }

  await page.goto("/admin?tab=marketing")
  await expect(page.getByTestId("marketing-contacts")).toBeVisible()

  // Import, through the same upload the real list goes through.
  await page.getByTestId("marketing-import").click()
  await page
    .locator('input[type="file"]')
    .first()
    .setInputFiles({
      name: "contacts.csv",
      mimeType: "text/csv",
      buffer: Buffer.from(`name,email\nGagan S,${address}\n`),
    })
  await expect(page.getByText(/1 added/)).toBeVisible()

  // Pick that one address, and only it.
  await page.getByTestId("marketing-search").fill(word)
  const row = page
    .getByTestId("marketing-contact-row")
    .filter({ hasText: word })
  await expect(row).toHaveCount(1)
  await row.getByRole("checkbox").check()
  await expect(page.getByTestId("marketing-selected-count")).toContainText(
    "1 of 1",
  )

  // Compose, preview, send.
  await page.getByRole("tab", { name: "Compose" }).click()
  await page.getByTestId("marketing-subject").fill(`Try this ${word}`)
  await page
    .getByTestId("marketing-body")
    .fill(`<p>Hi {{name}}, this is ${word}.</p>`)
  await page.getByTestId("marketing-preview-button").click()

  // The preview is the message: the greeting is resolved, not a placeholder.
  const frame = page.frameLocator('[data-testid="marketing-preview-frame"]')
  await expect(frame.locator("body")).toContainText("Hi Gagan")
  await expect(frame.locator("body")).toContainText("Unsubscribe")

  await expect(page.getByTestId("marketing-recipients")).toContainText(
    "1 recipient",
  )
  await page.getByTestId("marketing-send").click()

  // Sending moves to the status screen, which drains as the worker works.
  await expect(page.getByTestId("marketing-status")).toBeVisible()
  await expect(page.getByTestId("marketing-delivery-row")).toHaveCount(1)
  await expect(page.getByTestId("marketing-progress")).toContainText("1 sent", {
    timeout: 30_000,
  })

  // And it actually arrived, from the worker, with the link in the text part.
  const mail = await marketingEmail(request, address, word)
  expect(mail.subject).toContain(word)
  expect(mail.text).toContain("Hi Gagan,")
  const link = /\/unsubscribe\/([\w-]+)/.exec(mail.text)
  expect(link, "the message carries no unsubscribe link").not.toBeNull()

  // The link takes one click and says so.
  await page.goto(`/unsubscribe/${link?.[1]}`)
  await expect(page.getByTestId("unsubscribe-success")).toBeVisible()

  // And the admin list agrees.
  const contacts = await request.get(`${API}/admin/marketing/contacts`, {
    headers: auth,
    params: { q: word, subscribed: "false" },
  })
  const data = (await contacts.json()).data
  expect(data).toHaveLength(1)
  expect(data[0].subscribed).toBe(false)
})

test("a nonsense unsubscribe link says so rather than pretending", async ({
  page,
}) => {
  await page.goto("/unsubscribe/not-a-real-token")
  await expect(page.getByTestId("unsubscribe-failed")).toBeVisible()
})

test("the marketing endpoints need a credential", async ({ request }) => {
  /**
   * Asserted at the API rather than by looking for a missing tab: the route
   * already redirects non-superusers away from /admin entirely, and what
   * matters is that the endpoint behind it refuses too. 401 rather than 403,
   * because a bad token is nobody rather than somebody without permission;
   * the signed-in-but-not-an-admin case is covered in test_marketing.py.
   */
  const response = await request.get(`${API}/admin/marketing/contacts`, {
    headers: { Authorization: "Bearer not-a-token" },
  })
  expect(response.status()).toBe(401)
})
