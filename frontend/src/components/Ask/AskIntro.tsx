import { FileSearch, MessagesSquare, Pin, Quote } from "lucide-react"

import { Button } from "@/components/ui/button"

/** Generic starters: phrasing that suits any knowledge base, not this one. */
const EXAMPLES = [
  "How do I get set up?",
  "What changed recently?",
  "Who owns this and how do I reach them?",
]

/** What a single page is usually asked. */
const PAGE_EXAMPLES = [
  "Summarise this page",
  "What are the key dates and numbers?",
  "What does this page not cover?",
]

const POINTS = [
  {
    icon: FileSearch,
    title: "Searches everything",
    body: "Keyword and semantic search run together across whole pages, their summaries and their sections.",
  },
  {
    icon: Quote,
    title: "Answers with citations",
    body: "Every claim points at the page it came from, so you can check it in one click.",
  },
  {
    icon: MessagesSquare,
    title: "Keeps the thread",
    body: "Follow-ups remember what was asked, so “and in euros?” works. Every chat is kept in the rail beside this one.",
  },
]

interface AskIntroProps {
  onExample: (question: string) => void
  /** The page the next question is pinned to, if there is one. */
  pageTitle?: string
}

export function AskIntro({ onExample, pageTitle }: AskIntroProps) {
  const examples = pageTitle ? PAGE_EXAMPLES : EXAMPLES

  return (
    <div className="flex flex-col gap-5 rounded-lg border border-dashed px-6 py-8">
      <div>
        <h2 className="flex items-center gap-2 text-base font-medium">
          {pageTitle && <Pin className="size-4 text-muted-foreground" />}
          {pageTitle ? `Ask about “${pageTitle}”` : "Ask your knowledge base"}
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          {pageTitle
            ? "Nothing is searched: the answer is written from this page alone, which makes it the fastest way to ask."
            : "Put a question in your own words. The best matching pages are found first, then an answer is written from them."}
        </p>
      </div>

      {!pageTitle && (
        <dl className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          {POINTS.map((point) => (
            <div
              key={point.title}
              className="rounded-md border bg-muted/20 p-3"
            >
              <dt className="flex items-center gap-1.5 text-sm font-medium">
                <point.icon className="size-3.5 text-muted-foreground" />
                {point.title}
              </dt>
              <dd className="mt-1 text-sm text-muted-foreground">
                {point.body}
              </dd>
            </div>
          ))}
        </dl>
      )}

      <div className="flex flex-wrap items-center gap-2">
        {examples.map((example) => (
          <Button
            key={example}
            variant="outline"
            size="sm"
            onClick={() => onExample(example)}
            data-testid="ask-example"
          >
            {example}
          </Button>
        ))}
      </div>
    </div>
  )
}
