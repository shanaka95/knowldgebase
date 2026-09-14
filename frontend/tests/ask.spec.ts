import { expect, test } from "@playwright/test"

import {
  adminToken,
  createDocument,
  createNamespace,
  uid,
} from "./utils/api.ts"
import { openDocument } from "./utils/ui.ts"

/**
 * Ask, pinned to one page.
 *
 * Everything here goes through the pinned path on purpose: it needs no
 * embeddings and no search, so the test exercises the whole feature - the
 * button on the page, the thread, the follow-up, the history rail - without
 * waiting on the indexing pipeline.
 */

const PAGE = {
  title: "Connecting to the VPN",
  content:
    "<h2>Errors</h2><p>Error 407 means your VPN token has expired. " +
    "Request a new one from the IT portal; tokens last 30 days.</p>",
}

// A real model writes these answers, and a local one is not quick.
test.describe.configure({ mode: "serial" })
test.setTimeout(180_000)

async function seedPage(request: Parameters<typeof adminToken>[0]) {
  const token = await adminToken(request)
  const namespace = await createNamespace(request, token, {
    name: `Ask ${uid()}`,
  })
  const document = await createDocument(request, token, namespace.id, {
    title: `${PAGE.title} ${uid()}`,
    content: PAGE.content,
  })
  return { token, namespace, document }
}

test("a page hands its question to Ask, already pinned", async ({
  page,
  request,
}) => {
  const { namespace, document } = await seedPage(request)

  await openDocument(page, namespace.slug, document.id)
  await page.getByTestId("ask-about-page").click()

  await page.waitForURL(/\/ask\?.*doc=/)
  await expect(page.getByTestId("ask-pinned-page")).toContainText(
    document.title,
  )
  // The empty state says what pinning means, so nobody has to guess.
  await expect(page.getByText("this page alone")).toBeVisible()
})

test("an answer, a follow-up, and the thread they land in", async ({
  page,
  request,
}) => {
  const { document } = await seedPage(request)

  await page.goto(`/ask?doc=${document.id}`)
  await expect(page.getByTestId("ask-pinned-page")).toBeVisible()

  await page.getByTestId("ask-input").fill("What does error 407 mean?")
  await page.getByTestId("ask-submit").click()

  // The thread is created and named before the answer starts arriving.
  await page.waitForURL(/[?&]c=/, { timeout: 60_000 })
  await expect(page.getByTestId("ask-answer").first()).toBeVisible({
    timeout: 120_000,
  })
  await expect(page.getByTestId("ask-footer").first()).toContainText(
    "the one page you chose",
    { timeout: 120_000 },
  )

  // The newest turn shows its sources without being asked.
  await expect(page.getByTestId("ask-source").first()).toContainText(
    document.title,
  )
  await page.getByTestId("ask-sources-toggle").first().click()
  await expect(page.getByTestId("ask-source")).toHaveCount(0)
  await page.getByTestId("ask-sources-toggle").first().click()
  await expect(page.getByTestId("ask-source").first()).toBeVisible()

  const conversationUrl = page.url()

  await page.getByTestId("ask-input").fill("And how long do they last?")
  await page.getByTestId("ask-submit").click()
  await expect(page.getByTestId("ask-turn")).toHaveCount(2, {
    timeout: 120_000,
  })
  // The URL did not change: the follow-up joined the same thread.
  expect(page.url()).toBe(conversationUrl)

  // Reloading reads the thread back from the server, both turns intact.
  await page.reload()
  await expect(page.getByTestId("ask-turn")).toHaveCount(2, {
    timeout: 30_000,
  })
  await expect(page.getByTestId("ask-question").first()).toContainText(
    "What does error 407 mean?",
  )
})

test("the history rail opens, renames and deletes a thread", async ({
  page,
  request,
}) => {
  const { document } = await seedPage(request)

  await page.goto(`/ask?doc=${document.id}`)
  await page.getByTestId("ask-input").fill("Summarise this page")
  await page.getByTestId("ask-submit").click()
  await expect(page.getByTestId("ask-answer").first()).toBeVisible({
    timeout: 120_000,
  })

  const row = page
    .getByTestId("ask-history-item")
    .filter({ hasText: "Summarise this page" })
    .first()
  await expect(row).toBeVisible({ timeout: 30_000 })
  await expect(row).toHaveAttribute("data-active", "true")

  // A new thread clears the transcript but leaves the old one in the rail.
  await page.getByTestId("ask-new-chat").click()
  await expect(page.getByTestId("ask-turn")).toHaveCount(0)
  await expect(row).toBeVisible()

  // …and it opens again from the rail, with its answer.
  await row.click()
  await expect(page.getByTestId("ask-answer").first()).toBeVisible({
    timeout: 30_000,
  })

  await row.hover()
  await page.getByTestId("ask-history-menu").first().click({ force: true })
  await page.getByRole("menuitem", { name: "Rename" }).click()
  await page.getByTestId("ask-rename-input").fill("VPN troubleshooting")
  await page.getByTestId("ask-rename-input").press("Enter")
  const renamed = page
    .getByTestId("ask-history-item")
    .filter({ hasText: "VPN troubleshooting" })
    .first()
  await expect(renamed).toBeVisible()

  await renamed.hover()
  await page.getByTestId("ask-history-menu").first().click({ force: true })
  await page.getByRole("menuitem", { name: "Delete" }).click()
  await page.getByTestId("ask-confirm-delete").click()
  await expect(renamed).toBeHidden()
})
