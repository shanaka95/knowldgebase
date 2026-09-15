import { useQuery } from "@tanstack/react-query"
import { Check, Languages, Loader2, Zap } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { cn } from "@/lib/utils"
import {
  documentLanguagesQuery,
  useTranslateDocument,
} from "@/queries/documentVersions"

interface LanguagePickerProps {
  documentId: string
  /** The language being read, or null for the page as written. */
  reading: string | null
  onRead: (language: string | null) => void
  /** Translating is for the current version; an older one is read as written. */
  disabled?: boolean
}

/**
 * Read this page in another language.
 *
 * Opens on the language the page is actually written in, which is detected
 * when its text changes rather than asked for. Nothing is translated until
 * somebody picks a language, and what has already been translated *for this
 * version* is marked, because those open instantly and the rest take a moment.
 *
 * Editing a page leaves the new version with no translations: the words
 * changed, so last version's German no longer describes them.
 */
export function LanguagePicker({
  documentId,
  reading,
  onRead,
  disabled,
}: LanguagePickerProps) {
  const { data } = useQuery(documentLanguagesQuery(documentId))
  const translate = useTranslateDocument(documentId)

  const options = data?.options ?? []
  const available = new Set(data?.available ?? [])
  const source = data?.source_language ?? null
  const sourceName = data?.source_language_name ?? "As written"
  const currentName = reading
    ? (options.find((o) => o.code === reading)?.name ?? reading)
    : sourceName

  const pick = (code: string | null) => {
    if (code === null || code === source) {
      onRead(null)
      return
    }
    if (available.has(code)) {
      onRead(code)
      return
    }
    translate.mutate(code, {
      onSuccess: () => onRead(code),
      onError: (error) =>
        toast.error(
          error instanceof Error
            ? `Could not translate this page: ${error.message}`
            : "Could not translate this page",
        ),
    })
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant={reading ? "outline" : "ghost"}
          size="xs"
          className={cn("gap-1.5", !reading && "text-muted-foreground")}
          disabled={disabled}
          data-testid="language-picker"
        >
          {translate.isPending ? (
            <Loader2 className="size-3.5 animate-spin" />
          ) : (
            <Languages className="size-3.5" />
          )}
          {translate.isPending ? "Translating…" : currentName}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-64">
        <DropdownMenuLabel className="text-xs font-normal text-muted-foreground">
          {disabled
            ? "Older versions are read as they were written"
            : "Translated on demand, then kept for this version"}
        </DropdownMenuLabel>
        <DropdownMenuSeparator />

        <DropdownMenuItem onSelect={() => pick(null)}>
          <Check
            className={cn(
              "size-3.5 shrink-0",
              reading === null ? "opacity-100" : "opacity-0",
            )}
          />
          <span className="flex-1">{sourceName}</span>
          <span className="text-xs text-muted-foreground">as written</span>
        </DropdownMenuItem>
        <DropdownMenuSeparator />

        <div className="max-h-72 overflow-y-auto">
          {options
            .filter((option) => option.code !== source)
            .map((option) => (
              <DropdownMenuItem
                key={option.code}
                onSelect={() => pick(option.code)}
                data-testid="language-option"
              >
                <Check
                  className={cn(
                    "size-3.5 shrink-0",
                    reading === option.code ? "opacity-100" : "opacity-0",
                  )}
                />
                <span className="flex-1">{option.name}</span>
                {available.has(option.code) && (
                  <Zap
                    className="size-3 text-muted-foreground"
                    aria-label="Already translated"
                  />
                )}
              </DropdownMenuItem>
            ))}
        </div>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
