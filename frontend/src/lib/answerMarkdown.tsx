import type { ReactNode } from "react"

/**
 * Renders the light markdown the model replies in — paragraphs, bullet and
 * numbered lists, `**bold**`, `` `code` `` — plus inline `[2]` citations.
 *
 * Everything becomes React elements, never `dangerouslySetInnerHTML`: the model
 * writes this text, so nothing it emits can turn into markup.
 */

type Block =
  | { kind: "p"; lines: string[] }
  | { kind: "ul"; items: string[] }
  | { kind: "ol"; items: string[] }

const BULLET = /^\s*[-*•]\s+(.*)$/
const NUMBERED = /^\s*\d+[.)]\s+(.*)$/
const HEADING = /^\s*#{1,6}\s+(.*)$/

export function parseBlocks(text: string): Block[] {
  const blocks: Block[] = []
  let paragraph: string[] = []

  const flush = () => {
    if (paragraph.length) blocks.push({ kind: "p", lines: paragraph })
    paragraph = []
  }

  for (const raw of (text ?? "").split("\n")) {
    const line = raw.trimEnd()
    if (!line.trim()) {
      flush()
      continue
    }
    const bullet = BULLET.exec(line)
    const numbered = NUMBERED.exec(line)
    const heading = HEADING.exec(line)

    if (bullet) {
      flush()
      const last = blocks[blocks.length - 1]
      if (last?.kind === "ul") last.items.push(bullet[1])
      else blocks.push({ kind: "ul", items: [bullet[1]] })
    } else if (numbered) {
      flush()
      const last = blocks[blocks.length - 1]
      if (last?.kind === "ol") last.items.push(numbered[1])
      else blocks.push({ kind: "ol", items: [numbered[1]] })
    } else if (heading) {
      // The prompt asks for prose, but a stray heading should still read as text.
      flush()
      blocks.push({ kind: "p", lines: [`**${heading[1]}**`] })
    } else {
      paragraph.push(line)
    }
  }
  flush()
  return blocks
}

/** `**bold**`, `` `code` `` and `[n]` citations inside one line. */
const INLINE = /(\*\*[^*]+\*\*|`[^`]+`|\[\d{1,2}\])/g

interface InlineOptions {
  maxCitation: number
  onCite?: (index: number) => void
}

function renderInline(text: string, options: InlineOptions): ReactNode[] {
  return text.split(INLINE).map((part, i) => {
    const key = `${i}-${part}`
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4)
      return <strong key={key}>{part.slice(2, -2)}</strong>

    if (part.startsWith("`") && part.endsWith("`") && part.length > 2)
      return (
        <code
          key={key}
          className="rounded bg-muted px-1 py-0.5 font-mono text-[0.85em]"
        >
          {part.slice(1, -1)}
        </code>
      )

    const citation = /^\[(\d{1,2})\]$/.exec(part)
    if (citation) {
      const n = Number(citation[1])
      // A number the answer invented has nothing to point at; show it as text.
      if (n < 1 || n > options.maxCitation) return <span key={key}>{part}</span>
      return (
        <button
          key={key}
          type="button"
          onClick={() => options.onCite?.(n)}
          aria-label={`Jump to source ${n}`}
          data-testid="answer-citation"
          className="mx-0.5 inline-flex h-4 min-w-4 translate-y-[-2px] items-center justify-center rounded border border-primary/40 bg-primary/10 px-1 align-super font-mono text-[0.65rem] leading-none text-foreground transition hover:bg-primary/20"
        >
          {n}
        </button>
      )
    }
    return <span key={key}>{part}</span>
  })
}

export interface AnswerTextProps {
  text: string
  maxCitation: number
  onCite?: (index: number) => void
  className?: string
}

export function AnswerText({
  text,
  maxCitation,
  onCite,
  className,
}: AnswerTextProps) {
  const blocks = parseBlocks(text)
  const opts = { maxCitation, onCite }

  return (
    <div className={className}>
      {blocks.map((block, i) => {
        if (block.kind === "p")
          return (
            <p key={i} className="mb-3 last:mb-0">
              {block.lines.map((line, j) => (
                <span key={j}>
                  {j > 0 && " "}
                  {renderInline(line, opts)}
                </span>
              ))}
            </p>
          )
        const Tag = block.kind === "ul" ? "ul" : "ol"
        return (
          <Tag
            key={i}
            className={`mb-3 ml-5 flex flex-col gap-1 last:mb-0 ${
              block.kind === "ul" ? "list-disc" : "list-decimal"
            }`}
          >
            {block.items.map((item, j) => (
              <li key={j}>{renderInline(item, opts)}</li>
            ))}
          </Tag>
        )
      })}
    </div>
  )
}
