import {
  BookOpen,
  Braces,
  Copy,
  ExternalLink,
  TerminalSquare,
} from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { useCopyToClipboard } from "@/hooks/useCopyToClipboard"

const apiBase = import.meta.env.VITE_API_URL || window.location.origin

const curlExample = `# Create a page from Markdown with a personal API key
curl -X POST "${apiBase}/api/v1/documents" \\
  -H "Authorization: Bearer kb_your_api_key_here" \\
  -H "Content-Type: application/json" \\
  -d '{
    "namespace_id": "<namespace uuid>",
    "title": "Release notes",
    "content_format": "markdown",
    "content": "# v1.0\\n\\nFirst public release."
  }'`

const links = [
  {
    title: "Interactive API docs",
    description:
      "Swagger UI with every endpoint, schemas and a try-it console.",
    href: `${apiBase}/docs`,
    icon: Braces,
  },
  {
    title: "ReDoc reference",
    description: "Readable, printable reference of the same OpenAPI schema.",
    href: `${apiBase}/redoc`,
    icon: BookOpen,
  },
  {
    title: "API guide",
    description:
      "Authentication, scopes and a curl walkthrough (docs/API.md in the repository).",
    href: "https://github.com/",
    icon: TerminalSquare,
  },
]

export function Developer() {
  const [copied, copyToClipboard] = useCopyToClipboard()

  return (
    <div className="flex max-w-3xl flex-col gap-6">
      <div className="grid gap-4 sm:grid-cols-3">
        {links.map((l) => (
          <a
            key={l.title}
            href={l.href}
            target="_blank"
            rel="noopener noreferrer"
            className="group"
          >
            <Card className="h-full transition-colors group-hover:bg-accent/40">
              <CardHeader>
                <l.icon className="size-5 text-primary" />
                <CardTitle className="flex items-center gap-1.5 text-base">
                  {l.title}
                  <ExternalLink className="size-3.5 text-muted-foreground" />
                </CardTitle>
                <CardDescription>{l.description}</CardDescription>
              </CardHeader>
            </Card>
          </a>
        ))}
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Quick start</CardTitle>
          <CardDescription>
            Send <code className="font-mono">Authorization: Bearer kb_…</code>{" "}
            with a personal API key. Keys with the <em>write</em> scope can
            create and update pages; <em>read</em> keys can only fetch them.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="relative">
            <pre className="overflow-x-auto rounded-md border bg-muted p-4 text-xs leading-relaxed font-mono">
              {curlExample}
            </pre>
            <Button
              size="sm"
              variant="outline"
              className="absolute right-2 top-2"
              onClick={() => copyToClipboard(curlExample)}
            >
              <Copy />
              {copied ? "Copied" : "Copy"}
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

export default Developer
