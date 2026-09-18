import type { APIRequestContext } from "@playwright/test"
import { expect } from "@playwright/test"
import { API } from "./api.ts"

/**
 * Reading the mail the backend would have sent.
 *
 * The stack runs with `EMAIL_ENABLED=false`, so nothing leaves the machine:
 * every message is kept by the logging sender and handed back by the dev-only
 * `/private/emails/` endpoint (mounted only when FASTAPI_ENV=development).
 * That is what lets these tests answer a sign-in code or follow a confirmation
 * link exactly as a person reading their inbox would, rather than reaching
 * around the flows they are supposed to be testing.
 */
export interface CapturedEmail {
  to: string
  subject: string
  text: string
}

/** Messages for one address, newest first. */
export async function inbox(
  request: APIRequestContext,
  email: string,
): Promise<CapturedEmail[]> {
  const r = await request.get(`${API}/private/emails/`, {
    params: { to: email },
  })
  expect(r.ok(), await r.text()).toBeTruthy()
  return (await r.json()) as CapturedEmail[]
}

async function waitForEmail(
  request: APIRequestContext,
  email: string,
  matches: (message: CapturedEmail) => boolean,
  timeout = 15_000,
): Promise<CapturedEmail> {
  const deadline = Date.now() + timeout
  let last: CapturedEmail[] = []
  while (Date.now() < deadline) {
    last = await inbox(request, email)
    const found = last.find(matches)
    if (found) return found
    await new Promise((resolve) => setTimeout(resolve, 250))
  }
  throw new Error(
    `no matching message for ${email} within ${timeout}ms (saw: ${last
      .map((m) => m.subject)
      .join(", ")})`,
  )
}

/**
 * The latest sign-in code. Codes are strings, not numbers — a leading zero is
 * part of the code.
 */
export async function twoFactorCode(
  request: APIRequestContext,
  email: string,
  options: { not?: string } = {},
): Promise<string> {
  const message = await waitForEmail(request, email, (m) => {
    if (!/sign-in code/i.test(m.subject)) return false
    const found = m.text.match(/\b\d{4,8}\b/)
    return found !== null && found[0] !== options.not
  })
  const code = message.text.match(/\b\d{4,8}\b/)
  if (!code) throw new Error(`no code in: ${message.text}`)
  return code[0]
}

function tokenFrom(text: string, path: string): string {
  const url = text.match(new RegExp(`https?://\\S*${path}\\?token=\\S+`))
  if (!url) throw new Error(`no ${path} link in: ${text}`)
  const token = new URL(url[0]).searchParams.get("token")
  if (!token) throw new Error(`no token in: ${url[0]}`)
  return token
}

/** The token from the latest "confirm your address" link. */
export async function verificationToken(
  request: APIRequestContext,
  email: string,
): Promise<string> {
  const message = await waitForEmail(request, email, (m) =>
    /confirm your/i.test(m.subject),
  )
  return tokenFrom(message.text, "/verify-email")
}

/**
 * The token from the latest share-invitation link sent to an address that has
 * no account yet. Read from the outbox rather than the database, so the test
 * follows the same link the person would.
 */
export async function invitationToken(
  request: APIRequestContext,
  email: string,
): Promise<string> {
  const message = await waitForEmail(request, email, (m) =>
    /\/invite\?token=/.test(m.text),
  )
  return tokenFrom(message.text, "/invite")
}

/** The token from the latest "choose a new password" link. */
export async function passwordResetToken(
  request: APIRequestContext,
  email: string,
): Promise<string> {
  const message = await waitForEmail(request, email, (m) =>
    /^reset your/i.test(m.subject),
  )
  return tokenFrom(message.text, "/reset-password")
}

/** The latest reminder message for an address, matched on the note it names. */
export async function reminderEmail(
  request: APIRequestContext,
  email: string,
  needle: string,
): Promise<CapturedEmail> {
  return waitForEmail(
    request,
    email,
    (m) => /^Reminder:/.test(m.subject) && m.text.includes(needle),
    30_000,
  )
}

/** The latest campaign message for an address, matched on its subject. */
export async function marketingEmail(
  request: APIRequestContext,
  email: string,
  needle: string,
): Promise<CapturedEmail> {
  return waitForEmail(request, email, (m) => m.subject.includes(needle), 30_000)
}
