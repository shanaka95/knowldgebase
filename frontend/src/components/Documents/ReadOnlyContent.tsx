import { useQuery } from "@tanstack/react-query"
import { ArrowLeft, History, Languages } from "lucide-react"

import type { TranslationPublic } from "@/client"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import {
  documentVersionQuery,
  translationKey,
} from "@/queries/documentVersions"

interface ReadOnlyContentProps {
  documentId: string
  /** A past version being read, or null for the current one. */
  version: number | null
  /** A language being read, or null for the page as written. */
  language: string | null
  /** The version a translation would belong to. */
  currentVersion: number
  onBack: () => void
}

/**
 * The page as it was, or the page in another language.
 *
 * Read-only on purpose. Editing an old version would either rewrite history or
 * quietly fork it, and editing a translation would leave the page and its
 * translation disagreeing with no way to tell which is right. Coming back to
 * the current version is one click away.
 */
export function ReadOnlyContent({
  documentId,
  version,
  language,
  currentVersion,
  onBack,
}: ReadOnlyContentProps) {
  const showingVersion = version !== null
  const versionQuery = useQuery({
    ...documentVersionQuery(documentId, version ?? currentVersion),
    enabled: showingVersion,
  })
  // Put there by the translate mutation; this never fetches on its own, so a
  // language that has not been asked for yet simply shows nothing.
  const translation = useQuery<TranslationPublic>({
    queryKey: translationKey(documentId, currentVersion, language ?? ""),
    enabled: false,
  })

  const loading = showingVersion && versionQuery.isPending
  const body = showingVersion
    ? versionQuery.data?.content_html
    : translation.data?.content_html
  const heading = showingVersion
    ? versionQuery.data?.title
    : translation.data?.title

  return (
    <div className="flex flex-col gap-4" data-testid="document-read-only">
      <Alert>
        {showingVersion ? (
          <History className="size-4" />
        ) : (
          <Languages className="size-4" />
        )}
        <AlertDescription className="flex flex-wrap items-center justify-between gap-2">
          <span>
            {showingVersion
              ? `You are reading version ${version} of ${currentVersion}. It cannot be edited.`
              : "You are reading a translation. The page itself is unchanged."}
          </span>
          <Button
            variant="outline"
            size="sm"
            onClick={onBack}
            data-testid="read-only-back"
          >
            <ArrowLeft className="size-3.5" />
            Back to the current page
          </Button>
        </AlertDescription>
      </Alert>

      {loading && (
        <div className="flex flex-col gap-3">
          <Skeleton className="h-6 w-2/3" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-4/5" />
        </div>
      )}

      {!loading && heading && (
        <h2 className="text-xl font-semibold tracking-tight">{heading}</h2>
      )}

      {!loading && body !== undefined && (
        // The same sanitiser every saved page goes through has already run on
        // this, on the way in and again on the way out of the translator.
        <div
          className="kb-prose"
          data-testid="read-only-body"
          // biome-ignore lint/security/noDangerouslySetInnerHtml: server-sanitised page HTML, the same as the editor renders
          dangerouslySetInnerHTML={{ __html: body }}
        />
      )}

      {!loading && body === undefined && (
        <p className="text-sm text-muted-foreground">
          This content is no longer available. Go back to the current page.
        </p>
      )}
    </div>
  )
}
