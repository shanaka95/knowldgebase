import { expect, test } from "@playwright/test"

/**
 * When something breaks, the page has to say what.
 *
 * "Something went wrong" with no detail costs a round of guessing every time,
 * and it has. The message, the page, the build and the stack are all here and
 * copy in one press.
 */

test("a failing route explains itself and offers a reload", async ({
  page,
}) => {
  // Break the call the space page depends on, so the route genuinely throws
  // rather than the error state being simulated.
  await page.route("**/api/v1/namespaces/by-slug/**", (route) =>
    route.fulfill({ status: 500, json: { detail: "boom" } }),
  )
  // A 500 rather than a 404: a missing page has its own state, and what is
  // under test here is the one that has to explain itself.
  await page.goto("/s/any-space-at-all")

  const error = page.getByTestId("route-error")
  await expect(error).toBeVisible()

  // The blunt option, for when re-running the route cannot help.
  await expect(page.getByTestId("route-error-reload")).toBeVisible()

  // And the detail, folded away but present.
  await page.getByText("Technical details").click()
  const report = page.locator("[data-testid=route-error] pre")
  await expect(report).toContainText("Page:")
  await expect(report).toContainText("Error:")
  await expect(report).toContainText("Build:")
  await expect(page.getByTestId("route-error-copy")).toBeVisible()
})
