import { expect, test } from "@playwright/test"

import { firstSuperuser, firstSuperuserPassword } from "./config.ts"
import { API, adminToken, auth, uid } from "./utils/api.ts"
import { createUser } from "./utils/privateApi"
import { randomEmail, randomPassword } from "./utils/random"
import { logInUser } from "./utils/user"

/**
 * Groups, the limits they carry, and the fact that nobody in one is told.
 *
 * These run as the superuser via the saved session; the privacy case at the
 * bottom signs in as an ordinary account on purpose.
 */

test.setTimeout(120_000)

test.describe("Groups", () => {
  test("the default group is listed and cannot be deleted", async ({
    page,
  }) => {
    await page.goto("/admin?tab=groups")

    const card = page
      .getByTestId("group-card")
      .filter({ hasText: "Default" })
      .first()
    await expect(card).toBeVisible()
    await expect(card.getByTestId("delete-group")).toBeHidden()
  })

  test("a group can be created with a page limit, and it persists", async ({
    page,
  }) => {
    const name = `Contractors ${uid()}`
    await page.goto("/admin?tab=groups")

    await page.getByTestId("new-group").click()
    await page.getByTestId("group-name").fill(name)
    await page
      .getByTestId("new-group-card")
      .getByTestId("limit-max_pages")
      .fill("250")
    await page.getByTestId("create-group").click()

    const card = page.getByTestId("group-card").filter({ hasText: name })
    await expect(card).toBeVisible()
    await expect(card.getByTestId("limit-max_pages")).toHaveValue("250")

    await page.reload()
    await expect(
      page.getByTestId("group-card").filter({ hasText: name }),
    ).toBeVisible()
  })

  test("a group that sets nothing shows what its members would still get", async ({
    page,
  }) => {
    const name = `Inheritors ${uid()}`
    await page.goto("/admin?tab=groups")
    await page.getByTestId("new-group").click()
    await page.getByTestId("group-name").fill(name)
    await page.getByTestId("create-group").click()

    const card = page.getByTestId("group-card").filter({ hasText: name })
    await expect(card.getByTestId("limit-max_pages")).toHaveValue("")
    // The box is empty, and the placeholder says what they would get anyway.
    await expect(card.getByTestId("limit-max_pages")).toHaveAttribute(
      "placeholder",
      /100/,
    )
  })

  test("an account can be moved into a group and given an override", async ({
    page,
    request,
  }) => {
    const token = await adminToken(request)
    const email = randomEmail()
    await createUser({ email, password: randomPassword() })

    const name = `Team ${uid()}`
    const created = await request.post(`${API}/admin/user-groups/`, {
      headers: auth(token),
      data: { name, max_pages: 7 },
    })
    expect(created.ok(), await created.text()).toBeTruthy()

    await page.goto("/admin?tab=users")
    const row = page.getByRole("row").filter({ hasText: email })
    await expect(row).toBeVisible()
    await expect(row.getByTestId("user-group")).toHaveText("Default")

    await row.getByRole("button").last().click()
    await page.getByTestId("edit-assignment").click()
    await expect(page.getByTestId("assignment-dialog")).toBeVisible()

    await page.getByTestId("assignment-group").click()
    await page.getByRole("option", { name: new RegExp(name) }).click()
    await page.getByTestId("limit-max_pages").fill("500")
    await page.getByTestId("save-assignment").click()

    await expect(page.getByTestId("assignment-dialog")).toBeHidden()
    await expect(row.getByTestId("user-group")).toHaveText(name)
    // The override is in force, and the table says it is an override.
    await expect(row.getByTestId("user-pages")).toContainText("/ 500")
    await expect(row.getByTestId("user-pages")).toContainText("Override")
  })

  test("clearing an override falls back to the group's number", async ({
    page,
    request,
  }) => {
    const token = await adminToken(request)
    const email = randomEmail()
    const user = await createUser({ email, password: randomPassword() })

    const group = await (
      await request.post(`${API}/admin/user-groups/`, {
        headers: auth(token),
        data: { name: `Fallback ${uid()}`, max_pages: 42 },
      })
    ).json()
    await request.put(`${API}/admin/users/${user.id}/assignment`, {
      headers: auth(token),
      data: { group_id: group.id, overrides: { max_pages: 500 } },
    })

    await page.goto("/admin?tab=users")
    const row = page.getByRole("row").filter({ hasText: email })
    await expect(row.getByTestId("user-pages")).toContainText("/ 500")

    await row.getByRole("button").last().click()
    await page.getByTestId("edit-assignment").click()
    await page.getByTestId("limit-max_pages").fill("")
    await page.getByTestId("save-assignment").click()

    await expect(row.getByTestId("user-pages")).toContainText("/ 42")
    await expect(row.getByTestId("user-pages")).not.toContainText("Override")
  })
})

test.describe("Groups stay out of sight", () => {
  test.use({ storageState: { cookies: [], origins: [] } })

  test("a member is never told which group they are in", async ({
    page,
    request,
  }) => {
    const token = await adminToken(request)
    const sentinel = `ZZGRP${uid()}`
    const email = randomEmail()
    const password = randomPassword()
    const user = await createUser({ email, password })

    const group = await (
      await request.post(`${API}/admin/user-groups/`, {
        headers: auth(token),
        data: { name: sentinel, max_pages: 42 },
      })
    ).json()
    await request.post(`${API}/admin/user-groups/${group.id}/members`, {
      headers: auth(token),
      data: { user_ids: [user.id] },
    })

    // Nothing the browser receives while they use the app may carry it.
    const leaked: string[] = []
    page.on("response", async (response) => {
      if (!response.url().includes("/api/v1/")) return
      try {
        const body = await response.text()
        if (body.includes(sentinel)) leaked.push(response.url())
      } catch {
        /* a redirect or a body already consumed */
      }
    })

    await logInUser(page, email, password)
    await page.goto("/settings")
    await page.waitForLoadState("networkidle")

    expect(leaked, "a response carried the group's name").toEqual([])

    // And the administration of it is closed to them entirely.
    await page.goto("/admin?tab=groups")
    await expect(page.getByTestId("group-card")).toHaveCount(0)
    await expect(page).not.toHaveURL(/\/admin/)
  })

  test("a superuser still reaches the groups tab", async ({ page }) => {
    await logInUser(page, firstSuperuser, firstSuperuserPassword)
    await page.goto("/admin?tab=groups")
    await expect(page.getByTestId("group-card").first()).toBeVisible()
  })
})
