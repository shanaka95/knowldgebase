import { useQuery } from "@tanstack/react-query"
import { useState } from "react"

import { CampaignComposer } from "@/components/Marketing/CampaignComposer"
import { CampaignStatus } from "@/components/Marketing/CampaignStatus"
import { ContactsTable } from "@/components/Marketing/ContactsTable"
import { Badge } from "@/components/ui/badge"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import {
  campaignsQuery,
  marketingSettingsQuery,
} from "@/queries/adminMarketing"

/**
 * The marketing area: a list, a message, and what happened.
 *
 * Selection lives here rather than in the table, because it is the composer
 * that needs it and the two are different tabs. Sending moves straight to the
 * status screen: at one message a second there is something to watch, and the
 * only thing worse than a slow send is one with no sign it is happening.
 */
export function MarketingPanel() {
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [watching, setWatching] = useState<string | null>(null)
  const settings = useQuery(marketingSettingsQuery())
  const campaigns = useQuery(campaignsQuery())

  if (watching) {
    return (
      <CampaignStatus campaignId={watching} onBack={() => setWatching(null)} />
    )
  }

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <div className="flex min-w-0 flex-wrap items-center gap-2 text-muted-foreground text-sm">
        <span data-testid="marketing-counts">
          {settings.data?.subscribed ?? 0} subscribed of{" "}
          {settings.data?.contacts ?? 0} on the list
        </span>
      </div>

      <Tabs defaultValue="contacts">
        <TabsList className="h-auto flex-wrap">
          <TabsTrigger value="contacts">Contacts</TabsTrigger>
          <TabsTrigger value="compose">Compose</TabsTrigger>
          <TabsTrigger value="campaigns">Campaigns</TabsTrigger>
        </TabsList>

        <TabsContent value="contacts" className="pt-4">
          <ContactsTable selected={selected} onSelectedChange={setSelected} />
        </TabsContent>

        <TabsContent value="compose" className="pt-4">
          <CampaignComposer
            selected={selected}
            onSent={(id) => {
              setSelected(new Set())
              setWatching(id)
            }}
          />
        </TabsContent>

        <TabsContent value="campaigns" className="pt-4">
          <div className="flex min-w-0 flex-col gap-2">
            {(campaigns.data?.data ?? []).length === 0 && (
              <p className="text-muted-foreground text-sm">Nothing sent yet.</p>
            )}
            {(campaigns.data?.data ?? []).map((campaign) => (
              <button
                type="button"
                key={campaign.id}
                onClick={() => setWatching(campaign.id)}
                className="flex min-w-0 items-center gap-3 rounded-lg border p-3 text-left hover:bg-muted/40"
                data-testid="marketing-campaign-row"
              >
                <div className="min-w-0 flex-1">
                  <p className="wrap-anywhere font-medium text-sm">
                    {campaign.subject}
                  </p>
                  <p className="wrap-anywhere text-muted-foreground text-xs">
                    {campaign.sent_count} of {campaign.total} sent
                    {campaign.failed_count > 0 &&
                      `, ${campaign.failed_count} failed`}
                  </p>
                </div>
                <Badge variant="outline" className="shrink-0">
                  {campaign.status}
                </Badge>
              </button>
            ))}
          </div>
        </TabsContent>
      </Tabs>
    </div>
  )
}
