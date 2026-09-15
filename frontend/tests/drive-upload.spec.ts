import { expect, test } from "@playwright/test"

/**
 * Picking from Google Drive in the upload dialog.
 *
 * The data-sources reply is stubbed rather than a real Drive being connected:
 * what is under test is that the dialog offers the right thing for the state
 * the account is in, which is the part that can regress.
 */

const SOURCES = "**/api/v1/data-sources/"

function driveState(connected: boolean, available = true) {
  return {
    data: [
      {
        source_type: "google_drive",
        available,
        connected,
        account_email: connected ? "someone@example.com" : null,
        connected_at: null,
      },
    ],
    count: 1,
  }
}

async function openDialog(page: import("@playwright/test").Page) {
  await page.goto("/capture")
  await page.getByTestId("import-new").click()
  await expect(page.getByTestId("import-dialog")).toBeVisible()
}

test.describe("Uploading from Google Drive", () => {
  test("the choice is not offered when Drive is unavailable here", async ({
    page,
  }) => {
    await page.route(SOURCES, (route) =>
      route.fulfill({ json: driveState(false, false) }),
    )
    await openDialog(page)
    // A tab that leads nowhere is worse than no tab.
    await expect(page.getByTestId("source-drive")).toHaveCount(0)
    await expect(page.getByText("Drop PDFs or images here")).toBeVisible()
  })

  test("an unconnected Drive offers to connect rather than to pick", async ({
    page,
  }) => {
    await page.route(SOURCES, (route) =>
      route.fulfill({ json: driveState(false) }),
    )
    await openDialog(page)
    await page.getByTestId("source-drive").click()

    await expect(page.getByTestId("drive-pick")).toHaveCount(0)
    await expect(
      page.getByRole("link", { name: /Connect Google Drive/ }),
    ).toBeVisible()
  })

  test("a connected Drive offers the picker, and says the limits", async ({
    page,
  }) => {
    await page.route(SOURCES, (route) =>
      route.fulfill({ json: driveState(true) }),
    )
    await openDialog(page)
    await page.getByTestId("source-drive").click()

    await expect(page.getByTestId("drive-pick")).toBeVisible()
    // Both constraints stated before anybody picks anything.
    await expect(page.getByText(/PDFs and images, up to 50 MB each/)).toBeVisible()

    // The title field is hidden: a Drive import always names its own page.
    await expect(page.getByTestId("import-auto-title")).toBeHidden()
    // Notes still apply, and still reach the page.
    await expect(page.getByTestId("import-note")).toBeVisible()
    // Nothing to import until something is picked.
    await expect(page.getByTestId("import-submit")).toBeDisabled()
  })

  test("switching back to the device restores the dropzone", async ({
    page,
  }) => {
    await page.route(SOURCES, (route) =>
      route.fulfill({ json: driveState(true) }),
    )
    await openDialog(page)
    await page.getByTestId("source-drive").click()
    await expect(page.getByTestId("drive-pick")).toBeVisible()

    await page.getByTestId("source-device").click()
    await expect(page.getByText("Drop PDFs or images here")).toBeVisible()
    await expect(page.getByTestId("drive-pick")).toHaveCount(0)
  })
})
