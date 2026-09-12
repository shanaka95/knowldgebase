import { formatDistanceToNowStrict, isValid, parseISO } from "date-fns"

export function parseDate(value?: string | null): Date | null {
  if (!value) return null
  const d = parseISO(value)
  return isValid(d) ? d : null
}

export function relativeTime(value?: string | null): string {
  const d = parseDate(value)
  if (!d) return ""
  const diff = Date.now() - d.getTime()
  if (diff < 45_000) return "just now"
  return `${formatDistanceToNowStrict(d)} ago`
}

export function absoluteTime(value?: string | null): string {
  const d = parseDate(value)
  return d ? d.toLocaleString() : ""
}

export function shortDate(value?: string | null): string {
  const d = parseDate(value)
  return d
    ? d.toLocaleDateString(undefined, {
        year: "numeric",
        month: "short",
        day: "numeric",
      })
    : "—"
}
