import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Check, Copy, Globe, TriangleAlert } from "lucide-react"
import { useState } from "react"

import { DocumentsService } from "@/client"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Spinner } from "@/components/ui/spinner"
import { Switch } from "@/components/ui/switch"
import { useCopyToClipboard } from "@/hooks/useCopyToClipboard"
import useCustomToast from "@/hooks/useCustomToast"
import { queryKeys } from "@/lib/queryKeys"
import { cn } from "@/lib/utils"
import { publicDocumentQuery } from "@/queries/sharing"
import { handleError } from "@/utils"

interface PublicLinkSectionProps {
  documentId: string
}

/**
 * Publishing a page to anyone holding its link.
 *
 * Only offered to people who may share the page at all, because the backend
 * grants it on the same rule and a switch that always fails is worse than no
 * switch.
 */
export function PublicLinkSection({ documentId }: PublicLinkSectionProps) {
  const queryClient = useQueryClient()
  const [copied, copy] = useCopyToClipboard()
  const { showErrorToast, showSuccessToast } = useCustomToast()

  // Whether the page is published is asked of the public route itself — it
  // answers for the page id as readily as for the slug, and it is the same
  // answer a recipient would get. (`DocumentPublic.public_slug` is declared but
  // the document serializer never fills it in, so it cannot be used here.)
  const published = useQuery(publicDocumentQuery(documentId))
  /** What we just did, so the switch does not wait for a refetch to agree. */
  const [justToggled, setJustToggled] = useState<string | null | undefined>()
  const slug =
    justToggled !== undefined ? justToggled : (published.data?.slug ?? null)
  const isPublic = Boolean(slug)
  const url = slug ? `${window.location.origin}/p/${slug}` : ""

  const toggle = useMutation({
    mutationFn: async (next: boolean) => {
      if (!next) {
        await DocumentsService.unpublishDocument({
          path: { document_id: documentId },
        })
        return null
      }
      const link = await DocumentsService.publishDocument({
        path: { document_id: documentId },
      })
      return link.data.slug
    },
    onSuccess: (next) => {
      setJustToggled(next)
      showSuccessToast(
        next
          ? "This page is now readable by anyone with the link"
          : "The link has been withdrawn",
      )
      queryClient.invalidateQueries({
        queryKey: queryKeys.publicDocument(documentId),
      })
    },
    onError: handleError.bind(showErrorToast),
  })

  return (
    <section
      className="flex flex-col gap-3 rounded-md border p-3"
      data-testid="public-link-section"
      data-state={isPublic ? "on" : "off"}
    >
      <div className="flex items-start gap-3">
        <Globe className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
        <div className="min-w-0 flex-1">
          <Label htmlFor="public-link-switch" className="text-sm font-medium">
            Share by link
          </Label>
          <p className="text-xs text-muted-foreground">
            Publish a read-only copy of this page at its own address.
          </p>
        </div>
        {toggle.isPending && (
          <Spinner className="mt-1 size-4 text-muted-foreground" />
        )}
        <Switch
          id="public-link-switch"
          checked={isPublic}
          disabled={toggle.isPending || published.isPending}
          onCheckedChange={(next) => toggle.mutate(next)}
          data-testid="public-link-switch"
        />
      </div>

      {isPublic && (
        <>
          <div className="flex gap-2">
            <Input
              readOnly
              value={url}
              className="h-8 font-mono text-xs"
              aria-label="Public link"
              onFocus={(e) => e.target.select()}
              data-testid="public-link-url"
            />
            <Button
              type="button"
              variant="outline"
              size="sm"
              className={cn(copied === url && "border-success text-success")}
              onClick={() => void copy(url)}
              data-testid="public-link-copy"
            >
              {copied === url ? <Check /> : <Copy />}
              {copied === url ? "Copied" : "Copy"}
            </Button>
          </div>
          <p className="flex items-start gap-2 text-xs text-muted-foreground">
            <TriangleAlert className="mt-0.5 size-3.5 shrink-0 text-warning-foreground dark:text-warning" />
            <span>
              Anyone with this link can read the page without signing in. Turn
              the switch off to withdraw it.
            </span>
          </p>
        </>
      )}
    </section>
  )
}
