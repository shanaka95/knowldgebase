/**
 * Dictating a note, with the microphone and the model both faked.
 *
 * The browser APIs are replaced rather than driven with a fake capture device:
 * what is worth testing here is the component's three states and where the
 * words land, and a real MediaRecorder would only add a codec to the set of
 * things that can make this flaky. The upstream model is stubbed at the route,
 * so no audio leaves the machine and nothing is billed.
 */

import { expect, type Page, test } from "@playwright/test"

import { uid } from "./utils/api.ts"

/** A microphone that records nothing, quickly. */
async function fakeMicrophone(page: Page) {
  await page.addInitScript(() => {
    class FakeRecorder extends EventTarget {
      state = "inactive"
      mimeType = "audio/webm"
      ondataavailable: ((event: { data: Blob }) => void) | null = null
      onstop: (() => void) | null = null

      start() {
        this.state = "recording"
      }

      stop() {
        this.state = "inactive"
        this.ondataavailable?.({ data: new Blob(["x".repeat(2048)]) })
        this.onstop?.()
      }

      static isTypeSupported() {
        return true
      }
    }
    // @ts-expect-error replacing a browser global on purpose
    window.MediaRecorder = FakeRecorder
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: {
        getUserMedia: async () => ({
          getTracks: () => [{ stop() {} }],
        }),
      },
    })
  })
}

async function stubTheModel(page: Page, text: string) {
  await page.route("**/api/v1/notes/voice", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        enabled: true,
        max_seconds: 120,
        max_upload_mb: 20,
        credits_per_minute: 1.2,
      }),
    }),
  )
  await page.route("**/api/v1/notes/transcriptions", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        text,
        seconds: 4,
        model: "stub/whisper",
        credits: 0.08,
      }),
    }),
  )
}

test("a deployment with no speech model does not offer a microphone", async ({
  page,
}) => {
  // Better than a button that fails on the first recording. This is the real
  // state of the development stack, which has no ASR model configured.
  await page.goto("/notes")
  await expect(page.getByTestId("notes-composer")).toBeVisible()
  await expect(page.getByTestId("notes-dictate")).toBeHidden()
})

test("what you say ends up in the note", async ({ page }) => {
  const word = `marjoram${uid()}`
  await fakeMicrophone(page)
  await stubTheModel(page, `Remember the ${word}.`)

  await page.goto("/notes")
  await page.getByTestId("notes-composer-open").click()
  await page.getByTestId("notes-dictate").click()

  // Recording: a running clock and a way out of it.
  await expect(page.getByTestId("notes-dictate-clock")).toBeVisible()
  await expect(page.getByTestId("notes-dictate-cancel")).toBeVisible()
  await page.getByTestId("notes-dictate-stop").click()

  await expect(page.getByTestId("notes-composer-input")).toHaveValue(
    `Remember the ${word}.`,
  )

  await page.getByTestId("notes-composer-title").fill(`Dictated ${word}`)
  await page.getByTestId("notes-composer-save").click()

  const card = page.getByTestId("notes-card").filter({ hasText: word })
  await expect(card).toBeVisible()
})

test("a discarded recording is never sent", async ({ page }) => {
  await fakeMicrophone(page)
  await stubTheModel(page, "This should never appear.")

  let sent = 0
  await page.route("**/api/v1/notes/transcriptions", async (route) => {
    sent += 1
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        text: "This should never appear.",
        seconds: 4,
        model: "stub/whisper",
        credits: 0.08,
      }),
    })
  })

  await page.goto("/notes")
  await page.getByTestId("notes-composer-open").click()
  await page.getByTestId("notes-dictate").click()
  await page.getByTestId("notes-dictate-cancel").click()

  await expect(page.getByTestId("notes-dictate")).toBeVisible()
  await expect(page.getByTestId("notes-composer-input")).toHaveValue("")
  expect(sent, "a discarded recording was uploaded anyway").toBe(0)
})
