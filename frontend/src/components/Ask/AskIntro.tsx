import { FileSearch, Quote, ShieldCheck } from "lucide-react"

import { Button } from "@/components/ui/button"

/** Generic starters: phrasing that suits any knowledge base, not this one. */
const EXAMPLES = [
  "How do I get set up?",
  "What changed recently?",
  "Who owns this and how do I reach them?",
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
    icon: ShieldCheck,
    title: "Only your pages",
    body: "The model reads the excerpts it is given and nothing else. No pages on the topic means it says so.",
  },
]

export function AskIntro({ onExample }: { onExample: (q: string) => void }) {
  return (
    <div className="flex flex-col gap-5 rounded-lg border border-dashed px-6 py-8">
      <div>
        <h2 className="text-base font-medium">Ask your knowledge base</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Put a question in your own words. The best matching pages are found
          first, then an answer is written from them.
        </p>
      </div>

      <dl className="grid gap-3 sm:grid-cols-3">
        {POINTS.map((point) => (
          <div key={point.title} className="rounded-md border bg-muted/20 p-3">
            <dt className="flex items-center gap-1.5 text-sm font-medium">
              <point.icon className="size-3.5 text-muted-foreground" />
              {point.title}
            </dt>
            <dd className="mt-1 text-sm text-muted-foreground">{point.body}</dd>
          </div>
        ))}
      </dl>

      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm text-muted-foreground">Try:</span>
        {EXAMPLES.map((example) => (
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
