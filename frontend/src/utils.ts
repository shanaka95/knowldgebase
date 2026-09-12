import { AxiosError } from "axios"

/**
 * The backend's `detail` string is the message the user should see: it is
 * written for them, and for the security-sensitive flows it is deliberately
 * worded (and deliberately vague). Never replace it with wording of our own.
 */
export function extractErrorMessage(err: Error): string {
  if (err instanceof AxiosError) {
    const errDetail = (err.response?.data as any)?.detail
    if (Array.isArray(errDetail) && errDetail.length > 0) {
      return errDetail[0].msg
    }
    if (typeof errDetail === "string") {
      return errDetail
    }
    return err.message
  }
  return "Something went wrong."
}

/** The HTTP status behind an error, when there was a response at all. */
export function errorStatus(err: unknown): number | undefined {
  return err instanceof AxiosError ? err.response?.status : undefined
}

export const handleError = function (this: (msg: string) => void, err: Error) {
  const errorMessage = extractErrorMessage(err)
  this(errorMessage)
}

export const getInitials = (name: string): string => {
  return name
    .split(" ")
    .slice(0, 2)
    .map((word) => word[0])
    .join("")
    .toUpperCase()
}
