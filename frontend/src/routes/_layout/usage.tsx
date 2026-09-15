import { createFileRoute, useNavigate } from "@tanstack/react-router"
import { z } from "zod"

import { PageContainer, PageHeader } from "@/components/Layout/PageContainer"
import { MyUsagePanel } from "@/components/Usage/MyUsagePanel"
import {
  DEFAULT_RANGE_DAYS,
  lastDays,
  RangePicker,
} from "@/components/Usage/RangePicker"

export const Route = createFileRoute("/_layout/usage")({
  component: UsagePage,
  staticData: { crumb: "Usage" },
  // In the URL so a range survives a reload and can be linked to.
  validateSearch: z.object({
    from: z.string().optional().catch(undefined),
    to: z.string().optional().catch(undefined),
  }),
  head: () => ({ meta: [{ title: "Usage - PlusGPT" }] }),
})

function UsagePage() {
  const search = Route.useSearch()
  const navigate = useNavigate({ from: Route.fullPath })

  const fallback = lastDays(DEFAULT_RANGE_DAYS)
  const range = {
    from: search.from ?? fallback.from,
    to: search.to ?? fallback.to,
  }

  return (
    <PageContainer className="flex flex-col gap-6" size="wide">
      <PageHeader
        title="Usage"
        description="What you have asked of the knowledge base, and what it took to answer."
        actions={
          <RangePicker
            value={range}
            // Merged rather than replaced: this page has only a range today,
            // but replacing the whole search object is how a later parameter
            // quietly stops working.
            onChange={(next) =>
              navigate({
                search: (prev) => ({ ...prev, ...next }),
                replace: true,
              })
            }
          />
        }
      />
      <MyUsagePanel range={range} />
    </PageContainer>
  )
}
