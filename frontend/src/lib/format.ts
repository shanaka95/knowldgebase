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

/**
 * A large count, shortened the way a dashboard wants it.
 *
 * Token counts run to millions and the exact digit is never the point; the
 * order of magnitude is. The full number stays available as a `title`.
 */
export function compactNumber(value: number): string {
  if (!Number.isFinite(value)) return "—"
  return new Intl.NumberFormat(undefined, {
    notation: value >= 10_000 ? "compact" : "standard",
    maximumFractionDigits: value >= 10_000 ? 1 : 0,
  }).format(value)
}

export function fullNumber(value: number): string {
  return Number.isFinite(value) ? new Intl.NumberFormat().format(value) : "—"
}

/**
 * Money, from the integer nanodollars the API reports.
 *
 * Spend here is genuinely small — a question costs a thousandth of a cent — so
 * a plain currency format would round almost everything to $0.00 and make the
 * whole table read as free. Below a cent it shows more places rather than
 * fewer, and says "<$0.01" only when there is really nothing to show.
 */
export function costFromNanos(nanos: number): string {
  if (!Number.isFinite(nanos)) return "—"
  const dollars = nanos / 1_000_000_000
  if (dollars === 0) return "$0.00"
  if (dollars < 0.01)
    return dollars < 0.000_001 ? "<$0.000001" : `$${dollars.toFixed(6)}`
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: dollars < 1 ? 4 : 2,
  }).format(dollars)
}

/** A day as a chart axis wants it: short, and without the year. */
export function axisDate(value: string): string {
  const d = parseDate(value)
  return d
    ? d.toLocaleDateString(undefined, { month: "short", day: "numeric" })
    : value
}
