import { Search, Settings2, X } from "lucide-react"

import { NamespaceIcon } from "@/components/Namespaces/NamespaceIcon"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Separator } from "@/components/ui/separator"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { useNamespaces } from "@/hooks/useNamespaces"
import {
  CORPUS_HINTS,
  CORPUS_LABELS,
  DEFAULT_CANDIDATES,
  DEFAULT_RRF_K,
  METHOD_META,
  SEARCH_CORPORA,
  SEARCH_TARGETS,
  type SearchCorpus,
  type SearchTarget,
  TARGET_HINTS,
  TARGET_LABELS,
} from "@/lib/searchPrefs"
import { cn } from "@/lib/utils"

export const ALL_SPACES = "__all__"

interface SearchControlsProps {
  value: string
  onValueChange: (value: string) => void
  onSubmit: () => void
  bm25: boolean
  vector: boolean
  onMethodChange: (method: "bm25" | "vector", enabled: boolean) => void
  targets: SearchTarget[]
  onTargetsChange: (targets: SearchTarget[]) => void
  pages: boolean
  notes: boolean
  onCorpusChange: (corpus: SearchCorpus, enabled: boolean) => void
  space: string | undefined
  onSpaceChange: (space: string | undefined) => void
  rrfK: number
  onRrfKChange: (k: number) => void
  candidates: number
  onCandidatesChange: (n: number) => void
  onReset: () => void
}

export function SearchControls({
  value,
  onValueChange,
  onSubmit,
  bm25,
  vector,
  onMethodChange,
  targets,
  onTargetsChange,
  pages,
  notes,
  onCorpusChange,
  space,
  onSpaceChange,
  rrfK,
  onRrfKChange,
  candidates,
  onCandidatesChange,
  onReset,
}: SearchControlsProps) {
  const { data: namespaces } = useNamespaces()
  const advancedChanged =
    rrfK !== DEFAULT_RRF_K || candidates !== DEFAULT_CANDIDATES

  const toggleTarget = (target: SearchTarget, checked: boolean) => {
    const next = checked
      ? SEARCH_TARGETS.filter((t) => t === target || targets.includes(t))
      : targets.filter((t) => t !== target)
    // At least one place to look, always.
    if (next.length === 0) return
    onTargetsChange([...next])
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-2 sm:flex-row">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={value}
            onChange={(e) => onValueChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault()
                onSubmit()
              }
            }}
            placeholder="Search pages…"
            className="h-10 pr-9 pl-9"
            autoFocus
            data-testid="search-input"
          />
          {value && (
            <Button
              variant="ghost"
              size="icon-xs"
              className="absolute top-1/2 right-2 -translate-y-1/2"
              aria-label="Clear"
              onClick={() => onValueChange("")}
            >
              <X />
            </Button>
          )}
        </div>
        <Select
          value={space ?? ALL_SPACES}
          onValueChange={(v) => onSpaceChange(v === ALL_SPACES ? undefined : v)}
        >
          <SelectTrigger className="h-10 sm:w-52" aria-label="Space">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL_SPACES}>All spaces</SelectItem>
            {namespaces?.data.map((ns) => (
              <SelectItem key={ns.id} value={ns.id}>
                <span className="flex items-center gap-2">
                  <NamespaceIcon icon={ns.icon} color={ns.color} size="xs" />
                  {ns.name}
                </span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="flex flex-wrap items-center gap-x-5 gap-y-3 rounded-lg border bg-muted/30 px-4 py-3">
        <fieldset className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <legend className="sr-only">Search methods</legend>
          <span className="text-xs font-medium text-muted-foreground">
            Method
          </span>
          {(["bm25", "vector"] as const).map((method) => {
            const meta = METHOD_META[method]
            const checked = method === "bm25" ? bm25 : vector
            // Keeping one method on avoids a request the server would reject.
            const isLast = checked && !(method === "bm25" ? vector : bm25)
            return (
              <Tooltip key={method}>
                <TooltipTrigger asChild>
                  <div className="flex items-center gap-2">
                    <Checkbox
                      id={`method-${method}`}
                      checked={checked}
                      disabled={isLast}
                      onCheckedChange={(c) =>
                        onMethodChange(method, c === true)
                      }
                      data-testid={`method-${method}`}
                    />
                    <Label
                      htmlFor={`method-${method}`}
                      className={cn(
                        "cursor-pointer gap-1.5 text-sm font-normal",
                        isLast && "cursor-not-allowed opacity-70",
                      )}
                    >
                      <span
                        className={cn("size-2 rounded-full", meta.dot)}
                        aria-hidden
                      />
                      {meta.label}
                      <span className="text-muted-foreground">
                        ({meta.sublabel})
                      </span>
                    </Label>
                  </div>
                </TooltipTrigger>
                <TooltipContent className="max-w-64">
                  {meta.hint}
                  {isLast && (
                    <span className="mt-1 block text-muted-foreground">
                      At least one method must stay on.
                    </span>
                  )}
                </TooltipContent>
              </Tooltip>
            )
          })}
        </fieldset>

        <Separator orientation="vertical" className="hidden h-6 sm:block" />

        <fieldset className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <legend className="sr-only">Which corpus to search</legend>
          <span className="text-xs font-medium text-muted-foreground">
            Look in
          </span>
          {SEARCH_CORPORA.map((corpus) => {
            const checked = corpus === "pages" ? pages : notes
            // The last one checked cannot be unchecked: searching neither is a
            // 422, and the interface should say so rather than send it.
            const isLast = checked && !(corpus === "pages" ? notes : pages)
            return (
              <Tooltip key={corpus}>
                <TooltipTrigger asChild>
                  <div className="flex items-center gap-2">
                    <Checkbox
                      id={`corpus-${corpus}`}
                      checked={checked}
                      disabled={isLast}
                      onCheckedChange={(c) =>
                        onCorpusChange(corpus, c === true)
                      }
                      data-testid={`notes-corpus-${corpus}`}
                    />
                    <Label
                      htmlFor={`corpus-${corpus}`}
                      className={cn(
                        "cursor-pointer text-sm font-normal",
                        isLast && "cursor-not-allowed opacity-70",
                      )}
                    >
                      {CORPUS_LABELS[corpus]}
                    </Label>
                  </div>
                </TooltipTrigger>
                <TooltipContent className="max-w-64">
                  {isLast
                    ? "Search pages, notes, or both - not neither."
                    : CORPUS_HINTS[corpus]}
                </TooltipContent>
              </Tooltip>
            )
          })}
        </fieldset>

        <Separator orientation="vertical" className="hidden h-6 sm:block" />

        <fieldset
          className={cn(
            "flex flex-wrap items-center gap-x-4 gap-y-2",
            // Targets describe a page. With pages switched off they decide
            // nothing, and saying so is better than leaving them live.
            !pages && "pointer-events-none opacity-60",
          )}
        >
          <legend className="sr-only">Where to search</legend>
          <span className="text-xs font-medium text-muted-foreground">
            Search in
          </span>
          {SEARCH_TARGETS.map((target) => {
            const checked = targets.includes(target)
            const isLast = checked && targets.length === 1
            return (
              <Tooltip key={target}>
                <TooltipTrigger asChild>
                  <div className="flex items-center gap-2">
                    <Checkbox
                      id={`target-${target}`}
                      checked={checked}
                      disabled={isLast}
                      onCheckedChange={(c) => toggleTarget(target, c === true)}
                      data-testid={`target-${target}`}
                    />
                    <Label
                      htmlFor={`target-${target}`}
                      className={cn(
                        "cursor-pointer text-sm font-normal",
                        isLast && "cursor-not-allowed opacity-70",
                      )}
                    >
                      {TARGET_LABELS[target]}
                    </Label>
                  </div>
                </TooltipTrigger>
                <TooltipContent className="max-w-64">
                  {TARGET_HINTS[target]}
                </TooltipContent>
              </Tooltip>
            )
          })}
        </fieldset>

        <Popover>
          <PopoverTrigger asChild>
            <Button
              variant={advancedChanged ? "secondary" : "ghost"}
              size="sm"
              className="ml-auto"
              data-testid="search-advanced"
            >
              <Settings2 />
              Advanced
              {advancedChanged && (
                <span
                  className="size-1.5 rounded-full bg-primary"
                  aria-hidden
                />
              )}
            </Button>
          </PopoverTrigger>
          <PopoverContent align="end" className="w-80">
            <div className="flex flex-col gap-4">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="rrf-k" className="text-sm">
                  Fusion constant (k)
                </Label>
                <Input
                  id="rrf-k"
                  type="number"
                  min={1}
                  max={500}
                  value={rrfK}
                  onChange={(e) => onRrfKChange(Number(e.target.value))}
                  data-testid="rrf-k"
                />
                <p className="text-xs text-muted-foreground">
                  Lower makes each source's top hits more decisive; higher
                  rewards pages that several sources agree on. Default{" "}
                  {DEFAULT_RRF_K}.
                </p>
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="candidates" className="text-sm">
                  Candidates per source
                </Label>
                <Input
                  id="candidates"
                  type="number"
                  min={5}
                  max={200}
                  value={candidates}
                  onChange={(e) => onCandidatesChange(Number(e.target.value))}
                  data-testid="candidates"
                />
                <p className="text-xs text-muted-foreground">
                  How deep each source looks before fusion. Higher finds more,
                  slower. Default {DEFAULT_CANDIDATES}.
                </p>
              </div>
              <Button variant="outline" size="sm" onClick={onReset}>
                Reset to defaults
              </Button>
            </div>
          </PopoverContent>
        </Popover>
      </div>
    </div>
  )
}
