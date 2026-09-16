import { useQuery } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { ArrowRight, FileText, Share2 } from "lucide-react"

import { IndexHealth, WorkerBanner } from "@/components/Dashboard/IndexHealth"
import { NamespaceCards } from "@/components/Dashboard/NamespaceCards"
import { QuickCreate } from "@/components/Dashboard/QuickCreate"
import { RecentDocuments } from "@/components/Dashboard/RecentDocuments"
import { PageContainer } from "@/components/Layout/PageContainer"
import { Button } from "@/components/ui/button"
import useAuth from "@/hooks/useAuth"
import { sharedWithMeQuery } from "@/queries/shared"

export const Route = createFileRoute("/_layout/")({
  component: Dashboard,
  staticData: { crumb: "Dashboard" },
  head: () => ({ meta: [{ title: "Dashboard - PlusGPT" }] }),
})

function greetingForNow() {
  const hour = new Date().getHours()
  if (hour < 5) return "Working late"
  if (hour < 12) return "Good morning"
  if (hour < 18) return "Good afternoon"
  return "Good evening"
}

function SectionTitle({
  children,
  action,
}: {
  children: React.ReactNode
  action?: React.ReactNode
}) {
  return (
    <div className="flex items-center justify-between">
      <h2 className="text-sm font-medium text-muted-foreground">{children}</h2>
      {action}
    </div>
  )
}

function Dashboard() {
  const { user: currentUser } = useAuth()
  const name = currentUser?.full_name?.split(" ")[0] || currentUser?.email
  const { data: shared } = useQuery(sharedWithMeQuery())
  const sharedCount =
    (shared?.namespaces.length ?? 0) + (shared?.documents.length ?? 0)

  return (
    <PageContainer className="flex flex-col gap-8">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        {/*
          min-w-0 so the greeting can actually truncate: a flex item defaults to
          min-width:auto and refuses to shrink below its text, which pushed the
          buttons off the right of the page at tablet widths.
        */}
        <div className="min-w-0">
          <h1
            className="max-w-xl truncate text-2xl font-semibold tracking-tight"
            data-testid="dashboard-greeting"
          >
            {greetingForNow()}, {name} 👋
          </h1>
          <p className="mt-1 text-muted-foreground">
            Pick up where you left off, or start something new.
          </p>
        </div>
        <div className="shrink-0">
          <QuickCreate />
        </div>
      </div>

      <WorkerBanner />

      <section className="flex flex-col gap-3">
        <SectionTitle>Your spaces</SectionTitle>
        <NamespaceCards />
      </section>

      {/* minmax(0,…) on both tracks: a bare `auto` or `2fr` column is sized by
          its widest indivisible content, so one long page title stretched the
          column and, with it, the page. This lets the column be narrower than
          its content and leaves the truncating to the rows. */}
      <div className="grid grid-cols-1 gap-8 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <section className="flex flex-col gap-3">
          <SectionTitle
            action={
              <Button variant="ghost" size="sm" asChild>
                <Link to="/search" search={{ q: "" }}>
                  Search all <ArrowRight />
                </Link>
              </Button>
            }
          >
            Recent pages
          </SectionTitle>
          <RecentDocuments />
        </section>
        <section className="flex flex-col gap-3">
          <SectionTitle>Shared with you</SectionTitle>
          <Link
            to="/shared"
            className="flex items-center gap-3 rounded-lg border bg-card p-4 transition hover:border-primary/40 hover:shadow-sm"
            data-testid="dashboard-shared"
          >
            <span className="flex size-9 items-center justify-center rounded-md bg-primary/10 text-primary">
              <Share2 className="size-4" />
            </span>
            <span className="flex-1 text-sm">
              <span className="block font-medium">
                {sharedCount === 0
                  ? "Nothing shared yet"
                  : `${sharedCount} shared item${sharedCount === 1 ? "" : "s"}`}
              </span>
              <span className="text-xs text-muted-foreground">
                {shared?.namespaces.length ?? 0} spaces ·{" "}
                {shared?.documents.length ?? 0} pages
              </span>
            </span>
            <ArrowRight className="size-4 text-muted-foreground" />
          </Link>
          <SectionTitle>AI index</SectionTitle>
          <IndexHealth />
        </section>
      </div>
      <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <FileText className="size-3.5" />
        Every page is indexed for AI search automatically. The status pill on
        each page shows where it is up to.
      </p>
    </PageContainer>
  )
}
