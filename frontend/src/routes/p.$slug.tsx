import { createFileRoute, Link as RouterLink } from "@tanstack/react-router"

import { Appearance } from "@/components/Common/Appearance"
import { APP_NAME, APP_TAGLINE, Logo } from "@/components/Common/Logo"
import { DocumentTypeBadge } from "@/components/Documents/DocumentTypeBadge"
import { Skeleton } from "@/components/ui/skeleton"
import { relativeTime } from "@/lib/format"
import { publicDocumentQuery } from "@/queries/sharing"
import { extractErrorMessage } from "@/utils"

export const Route = createFileRoute("/p/$slug")({
  component: PublicDocumentRoute,
  // A sibling of /login rather than a child of the authenticated layout, and
  // the only query it runs needs no token: the link is the whole credential.
  loader: ({ context: { queryClient }, params }) =>
    queryClient.ensureQueryData(publicDocumentQuery(params.slug)),
  head: ({ loaderData }) => ({
    meta: [
      { title: loaderData ? `${loaderData.title} - ${APP_NAME}` : APP_NAME },
      // A shared link is meant for the people it was sent to, not for crawlers.
      { name: "robots", content: "noindex" },
    ],
  }),
  pendingComponent: PublicPending,
  errorComponent: PublicUnavailable,
})

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-svh flex-col bg-background">
      <header className="flex items-center justify-between gap-4 border-b px-4 py-3 md:px-8">
        <Logo variant="responsive" asLink={false} />
        <Appearance />
      </header>
      <main className="flex flex-1 justify-center px-4 py-8 md:px-8 md:py-12">
        <div className="kb-editor-column flex w-full min-w-0 flex-col gap-6">
          {children}
        </div>
      </main>
      <footer className="border-t px-4 py-6 text-center text-xs text-muted-foreground md:px-8">
        <RouterLink to="/" className="hover:text-foreground">
          Published with {APP_NAME} — {APP_TAGLINE}
        </RouterLink>
      </footer>
    </div>
  )
}

function PublicPending() {
  return (
    <Shell>
      <Skeleton className="h-9 w-2/3" />
      <Skeleton className="h-4 w-40" />
      <div className="flex flex-col gap-3">
        {[0, 1, 2, 3, 4].map((i) => (
          <Skeleton key={i} className="h-4 w-full" />
        ))}
      </div>
    </Shell>
  )
}

function PublicUnavailable({ error }: { error: unknown }) {
  return (
    <Shell>
      <div
        className="flex flex-col items-center gap-2 py-16 text-center"
        data-testid="public-document-missing"
      >
        <h1 className="text-2xl font-bold">This page isn't available</h1>
        <p className="text-sm text-muted-foreground">
          {error instanceof Error
            ? extractErrorMessage(error)
            : "No page is shared at this link."}
        </p>
      </div>
    </Shell>
  )
}

function PublicDocumentRoute() {
  const document = Route.useLoaderData()

  return (
    <Shell>
      <article
        className="flex flex-col gap-6"
        data-testid="public-document"
        data-slug={document.slug}
      >
        <header className="flex flex-col gap-3">
          <h1
            className="text-3xl font-semibold tracking-tight"
            data-testid="public-document-title"
          >
            {document.title}
          </h1>
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <DocumentTypeBadge type={document.doc_type} />
            {document.shared_by && (
              <span data-testid="public-document-sharer">
                Shared by {document.shared_by}
              </span>
            )}
            {document.updated_at && (
              <span>· updated {relativeTime(document.updated_at)}</span>
            )}
          </div>
        </header>

        {/* The markup is sanitised on the way in (the backend runs every saved
            page through nh3), so this renders exactly what the editor renders. */}
        <div
          className="kb-prose"
          // biome-ignore lint/security/noDangerouslySetInnerHtml: server-sanitised page content, the same markup the editor shows
          dangerouslySetInnerHTML={{ __html: document.content_html }}
        />
      </article>
    </Shell>
  )
}
