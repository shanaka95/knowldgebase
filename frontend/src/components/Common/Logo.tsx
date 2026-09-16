import { Link } from "@tanstack/react-router"

import { cn } from "@/lib/utils"

export const APP_NAME = "PlusGPT"
export const APP_TAGLINE = "a personal knowledge management system"

/**
 * The brand mark and wordmark, drawn rather than loaded.
 *
 * Inline so both follow `currentColor` — the logo then reads correctly in light
 * and dark themes without shipping two files — and so neither costs a request
 * on first paint, where the sidebar and the sign-in page both show it.
 *
 * `public/favicon.svg` carries the same mark, reversed out of the brand tile.
 */

const MARK_PATHS = [
  "M8.203,42.885l44.208,53.898c0,0-11.808-53.9,5.148-93.566L8.203,42.885z",
  "M54.326,32.822c0,0-6.759,30.048-0.702,55.786c0,0-2.12-29.068,31.49-66.616L54.326,32.822z",
  "M55.752,93.512c0,0-0.625-21.529,12.094-41.182h23.951C91.797,52.33,71.204,63.594,55.752,93.512z",
]

// One path for the whole word. Its own coordinate space is roughly 90 x 15,
// which the viewBox below crops to with a little air for the descender.
const WORDMARK_PATH =
  "M2.06 20 l0 -14 l4.92 0 c3.42 0 5.38 1.58 5.38 4.2 l0 0.04 c0 2.72 -2.08 4.26 -5.46 4.26 l-4.4 0 l0 5.5 l-0.44 0 z M2.5 14.1 l4.4 0 c3.1 0 5.02 -1.36 5.02 -3.84 l0 -0.04 c0 -2.38 -1.84 -3.82 -4.98 -3.82 l-4.44 0 l0 7.7 z M15.44 20 l0 -14 l0.44 0 l0 13.6 l8.6 0 l0 0.4 l-9.04 0 z M32.16 20.22 c-3.34 0 -5.66 -2.12 -5.66 -6.42 l0 -7.8 l0.44 0 l0 7.8 c0 4.02 2.14 6.02 5.24 6.02 c3.14 0 5.2 -2 5.2 -6 l0 -7.82 l0.44 0 l0 7.8 c0 4.28 -2.28 6.42 -5.66 6.42 z M46.4 20.2 c-2.14 0 -4.04 -0.82 -5.54 -2.24 l0.32 -0.32 c1.42 1.38 3.22 2.16 5.26 2.16 c2.62 0 4.3 -1.42 4.3 -3.3 l0 -0.04 c0 -1.72 -1.04 -2.64 -4.58 -3.36 c-3.46 -0.7 -4.78 -1.72 -4.78 -3.68 l0 -0.04 c0 -1.96 1.92 -3.58 4.56 -3.58 c1.84 0 3.48 0.62 4.76 1.6 l-0.28 0.36 c-1.24 -0.94 -2.8 -1.56 -4.52 -1.56 c-2.46 0 -4.08 1.52 -4.08 3.16 l0 0.04 c0 1.7 1.08 2.6 4.52 3.3 c3.64 0.74 4.84 1.84 4.84 3.74 l0 0.04 c0 2.08 -1.82 3.72 -4.78 3.72 z M60.88 20.24 c-4.38 0 -6.9 -3.3 -6.9 -7.2 l0 -0.04 c0 -3.74 2.66 -7.24 6.92 -7.24 c2.14 0 3.46 0.64 4.86 1.8 l-0.28 0.34 c-1.3 -1.06 -2.6 -1.74 -4.6 -1.74 c-3.94 0 -6.46 3.36 -6.46 6.82 l0 0.04 c0 3.64 2.4 6.82 6.48 6.82 c2.08 0 3.8 -0.92 4.98 -1.92 l0 -4.5 l-5.16 0 l0 -0.44 l5.6 0 l0 5.1 c-1.32 1.2 -3.18 2.16 -5.44 2.16 z M70.16 20 l0 -14 l4.92 0 c3.42 0 5.38 1.58 5.38 4.2 l0 0.04 c0 2.72 -2.08 4.26 -5.46 4.26 l-4.4 0 l0 5.5 l-0.44 0 z M70.6 14.1 l4.4 0 c3.1 0 5.02 -1.36 5.02 -3.84 l0 -0.04 c0 -2.38 -1.84 -3.82 -4.98 -3.82 l-4.44 0 l0 7.7 z M87.06 20 l0 -13.6 l-5.06 0 l0 -0.4 l10.56 0 l0 0.4 l-5.06 0 l0 13.6 l-0.44 0 z"

interface LogoProps {
  variant?: "full" | "icon" | "responsive"
  className?: string
  asLink?: boolean
}

function Mark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 100 100"
      className={cn("size-7 shrink-0", className)}
      fill="currentColor"
      aria-hidden="true"
      focusable="false"
    >
      {MARK_PATHS.map((d) => (
        <path key={d} d={d} />
      ))}
    </svg>
  )
}

function Wordmark({ className }: { className?: string }) {
  return (
    <svg
      // Cropped to the glyphs: the source art carried the mark's whitespace
      // too, which would have left the word floating away from it.
      viewBox="2 5 91 16"
      className={cn("h-4 w-auto shrink-0", className)}
      fill="currentColor"
      aria-hidden="true"
      focusable="false"
    >
      {/*
        The source art draws the letters as hairline outlines, which all but
        vanish beside the mark at interface sizes. Stroking the same path in the
        same colour thickens every stem evenly, closer to a text weight and
        without redrawing the letterforms.

        The width is measured, not guessed: a stroke grows a stem on both sides,
        so it is not proportional to the weight you see. 1.2 paints half again
        as much ink as the 0.65 it replaces, which is the 1.5x asked for, and it
        is the most the counters in P, G and S take before they start to close
        at 14px.
      */}
      <path
        d={WORDMARK_PATH}
        stroke="currentColor"
        strokeWidth={1.2}
        strokeLinejoin="round"
      />
    </svg>
  )
}

export function Logo({
  variant = "full",
  className,
  asLink = true,
}: LogoProps) {
  const content =
    variant === "responsive" ? (
      // The mark keeps its place on the icon rail when the sidebar collapses,
      // so it stays on the same vertical line as the navigation icons below.
      <span className={cn("flex items-center gap-2.5", className)}>
        <Mark className="size-6" />
        <Wordmark className="h-3.5 group-data-[collapsible=icon]:hidden" />
      </span>
    ) : variant === "icon" ? (
      <Mark className={className} />
    ) : (
      <span className={cn("flex items-center gap-3", className)}>
        <Mark className="size-9" />
        <Wordmark className="h-5" />
      </span>
    )

  // The name is carried once, here, rather than by each drawing: the mark and
  // the word together are one thing, and a screen reader should hear it once.
  const labelled = (
    <>
      <span className="sr-only">{APP_NAME}</span>
      {content}
    </>
  )

  if (!asLink) {
    return <span className="inline-flex items-center">{labelled}</span>
  }

  return (
    <Link to="/" className="inline-flex items-center" aria-label={APP_NAME}>
      {content}
    </Link>
  )
}
