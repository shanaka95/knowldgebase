import { Fragment } from "react"

/**
 * Renders a search snippet that may contain `<mark>` tags from Postgres
 * ts_headline. Every other tag is stripped; text is rendered as text.
 */
export function Snippet({
  html,
  className,
}: {
  html: string
  className?: string
}) {
  const stripped = html.replace(/<(?!\/?mark\b)[^>]*>/gi, "")
  const parts = stripped.split(/(<mark>.*?<\/mark>)/gi)
  return (
    <span className={className}>
      {parts.map((part, i) => {
        const m = /^<mark>(.*?)<\/mark>$/i.exec(part)
        return m ? (
          <mark
            key={i}
            className="rounded-sm bg-warning/40 px-0.5 text-foreground"
          >
            {decode(m[1])}
          </mark>
        ) : (
          <Fragment key={i}>{decode(part)}</Fragment>
        )
      })}
    </span>
  )
}

const NAMED_ENTITIES: Record<string, string> = {
  lt: "<",
  gt: ">",
  quot: '"',
  apos: "'",
  nbsp: " ",
}

function decode(text: string) {
  return (
    text
      // numeric entities, decimal and hex — the server escapes apostrophes as
      // &#x27;, so a hard-coded list of named entities is not enough
      .replace(/&#(\d+);/g, (_, code) => String.fromCodePoint(Number(code)))
      .replace(/&#x([0-9a-f]+);/gi, (_, code) =>
        String.fromCodePoint(Number.parseInt(code, 16)),
      )
      .replace(/&(lt|gt|quot|apos|nbsp);/g, (_, name) => NAMED_ENTITIES[name])
      // last, so a literal "&amp;lt;" survives as "&lt;"
      .replace(/&amp;/g, "&")
  )
}
