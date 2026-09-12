import { expect, test } from "@playwright/test"
import { API, auth, uid } from "./utils/api.ts"

test.describe("MCP settings", () => {
  test("creating a connection shows the key once with a pasteable config", async ({
    page,
    request,
  }) => {
    await page.goto("/settings?tab=mcp")
    const panel = page.getByTestId("mcp-settings")
    await expect(panel).toContainText("Model Context Protocol")
    await expect(panel).toContainText("Search your pages")
    await expect(panel).toContainText("Upload PDFs and images")

    const name = `Claude ${uid()}`
    await page.getByTestId("create-mcp-connection").click()
    const dialog = page.getByTestId("create-api-key-dialog")
    // the scope is fixed for MCP, so the permission chooser is not offered
    await expect(dialog.getByTestId("api-key-scope-read")).toHaveCount(0)
    await dialog.getByTestId("api-key-name").fill(name)
    await dialog.getByTestId("api-key-submit").click()

    const key = await dialog.getByTestId("api-key-value").inputValue()
    expect(key.startsWith("kb_")).toBeTruthy()
    await expect(dialog).toContainText("You won't see this key again")

    const config = JSON.parse(
      (await dialog.getByTestId("mcp-config").textContent()) ?? "{}",
    )
    const origin = new URL(page.url()).origin
    expect(config.mcpServers.plusgpt.type).toBe("http")
    expect(config.mcpServers.plusgpt.url).toBe(`${origin}/mcp`)
    expect(config.mcpServers.plusgpt.headers.Authorization).toBe(
      `Bearer ${key}`,
    )

    await dialog.getByTestId("mcp-config-copy").click()
    await expect(dialog.getByTestId("mcp-config-copy")).toContainText("Copied")
    await dialog.getByTestId("api-key-done").click()
    await expect(dialog).toBeHidden()

    // the connection is listed, and its key really can write
    const row = page.getByTestId("mcp-connection-row").filter({ hasText: name })
    await expect(row).toBeVisible()
    await expect(row).toContainText("read & write")

    const created = await request.post(`${API}/namespaces/`, {
      headers: auth(key),
      data: { name: `Via MCP ${uid()}` },
    })
    expect(created.status()).toBe(200)

    // revoking it from the MCP tab cuts the assistant off
    await row.getByTestId("api-key-revoke").click()
    await page.getByTestId("api-key-revoke-confirm").click()
    await expect(
      page.getByTestId("mcp-connection-row").filter({ hasText: name }),
    ).toHaveCount(0)
    const after = await request.get(`${API}/namespaces/`, {
      headers: auth(key),
    })
    expect(after.status()).toBe(403)
  })

  test("MCP connections are marked among the account's API keys", async ({
    page,
  }) => {
    await page.goto("/settings?tab=mcp")
    const name = `Cursor ${uid()}`
    await page.getByTestId("create-mcp-connection").click()
    const dialog = page.getByTestId("create-api-key-dialog")
    await dialog.getByTestId("api-key-name").fill(name)
    await dialog.getByTestId("api-key-submit").click()
    await expect(dialog.getByTestId("api-key-value")).toBeVisible()
    await dialog.getByTestId("api-key-done").click()

    await page.goto("/settings?tab=api-keys")
    await expect(
      page.getByTestId("api-key-row").filter({ hasText: `MCP · ${name}` }),
    ).toBeVisible()
  })
})
