import { expect, test } from "@playwright/test"

import { uid } from "./utils/api.ts"

/**
 * Making the place while you are filing the thing.
 *
 * Discovering that the folder you want does not exist is the normal case, and
 * the alternative was abandoning the upload, going elsewhere, and starting
 * again. Both lists can now create what they are missing, and select it.
 */

test.setTimeout(120_000)

// Serial: every test here adds a space or a folder to the same account, and
// the lists they assert against are the lists the others are changing.
test.describe.configure({ mode: "serial" })

async function openUpload(page: import("@playwright/test").Page) {
  await page.goto("/capture")
  await page.getByTestId("import-new").click()
  await expect(page.getByTestId("import-dialog")).toBeVisible()
}

test.describe("Creating a destination while uploading", () => {
  test("a space can be made from the space list and is selected", async ({
    page,
  }) => {
    await openUpload(page)
    const name = `Filed ${uid()}`

    await page.getByTestId("import-space-select").click()
    await page.getByTestId("import-new-space-option").click()

    const field = page.getByTestId("import-new-space")
    // Radix restores focus to the trigger as the dropdown closes, so the input
    // claims it a tick later. Waiting for that is the point: typing should not
    // need a click first.
    await expect(field).toBeFocused({ timeout: 5_000 })
    await field.fill(name)
    await field.press("Enter")

    // Back to the dropdown, with the new space chosen.
    await expect(page.getByTestId("import-space-select")).toContainText(name)
  })

  test("a folder can be made from the folder list and is selected", async ({
    page,
  }) => {
    await openUpload(page)
    const name = `Scans ${uid()}`

    await page.getByTestId("import-folder-select").click()
    await page.getByTestId("import-new-folder-option").click()

    const field = page.getByTestId("import-new-folder")
    await expect(field).toBeFocused({ timeout: 5_000 })
    await field.fill(name)
    await page.getByTestId("import-new-folder-confirm").click()

    await expect(page.getByTestId("import-folder-select")).toContainText(name)
  })

  test("the option says where the folder will go", async ({ page }) => {
    await openUpload(page)
    await page.getByTestId("import-folder-select").click()
    // At the root by default, and it says so rather than leaving it to guess.
    await expect(page.getByTestId("import-new-folder-option")).toContainText(
      "the space root",
    )
  })

  test("escape goes back without creating anything", async ({ page }) => {
    await openUpload(page)
    await page.getByTestId("import-folder-select").click()
    await page.getByTestId("import-new-folder-option").click()

    const field = page.getByTestId("import-new-folder")
    await field.fill("Not wanted")
    await field.press("Escape")

    // And crucially the upload dialog is still open: Escape here means "not
    // this name", never "not this upload" - the files were already chosen.
    await expect(page.getByTestId("import-dialog")).toBeVisible()
    await expect(page.getByTestId("import-folder-select")).toBeVisible()
    await expect(page.getByTestId("import-new-folder")).toHaveCount(0)
  })

  test("an empty name cannot be submitted", async ({ page }) => {
    await openUpload(page)
    await page.getByTestId("import-space-select").click()
    await page.getByTestId("import-new-space-option").click()

    await expect(page.getByTestId("import-new-space-confirm")).toBeDisabled()
    await page.getByTestId("import-new-space").fill("   ")
    await expect(page.getByTestId("import-new-space-confirm")).toBeDisabled()
  })
})
