import {
  queryOptions,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query"
import { toast } from "sonner"

import {
  AdminMarketingService,
  type CampaignCreate,
  type CampaignPreview,
  type CampaignPublic,
  type CampaignsPublic,
  type DeliveriesPublic,
  type MarketingContactsPublic,
  type MarketingSettings,
} from "@/client"
import { queryKeys } from "@/lib/queryKeys"

export interface ContactFilters {
  q?: string
  /** true: still on the list. false: has unsubscribed. undefined: both. */
  subscribed?: boolean
  skip?: number
  limit?: number
}

function contactQuery(filters: ContactFilters) {
  return {
    q: filters.q?.trim() || undefined,
    subscribed: filters.subscribed,
    skip: filters.skip ?? 0,
    limit: filters.limit ?? 50,
  }
}

/** Which addresses may be sent from, and how big the list is. */
export function marketingSettingsQuery() {
  return queryOptions({
    queryKey: queryKeys.admin.marketing.settings(),
    queryFn: async (): Promise<MarketingSettings> =>
      (await AdminMarketingService.readMarketingSettings()).data,
  })
}

/** A starting point for a new campaign, fetched rather than hard-coded here. */
export function marketingTemplateQuery() {
  return queryOptions({
    queryKey: queryKeys.admin.marketing.template(),
    queryFn: async () =>
      (await AdminMarketingService.readDefaultTemplate()).data,
    staleTime: Number.POSITIVE_INFINITY,
  })
}

export function contactsQuery(filters: ContactFilters) {
  return queryOptions({
    queryKey: queryKeys.admin.marketing.contacts(contactQuery(filters)),
    queryFn: async (): Promise<MarketingContactsPublic> =>
      (
        await AdminMarketingService.readContacts({
          query: contactQuery(filters),
        })
      ).data,
  })
}

/**
 * Every id matching the current filter.
 *
 * Fetched rather than inferred, because "select all" has to mean everybody and
 * the table only ever holds one page. Only enabled while the box is ticked, so
 * the list is not pulled down on the off chance.
 */
export function contactIdsQuery(filters: ContactFilters, enabled: boolean) {
  const query = {
    q: filters.q?.trim() || undefined,
    subscribed: filters.subscribed,
  }
  return queryOptions({
    queryKey: queryKeys.admin.marketing.contactIds(query),
    queryFn: async (): Promise<string[]> =>
      (await AdminMarketingService.readContactIds({ query })).data,
    enabled,
  })
}

export function campaignsQuery() {
  return queryOptions({
    queryKey: queryKeys.admin.marketing.campaigns(),
    queryFn: async (): Promise<CampaignsPublic> =>
      (await AdminMarketingService.readCampaigns()).data,
  })
}

/**
 * One campaign, refreshed while it is still going out.
 *
 * Polling is switched off the moment it is not sending, so a finished campaign
 * sitting open in a tab costs nothing. Same shape as the pairing dialog, which
 * is the codebase's one other live-progress screen.
 */
export function campaignQuery(id: string, live: boolean) {
  return queryOptions({
    queryKey: queryKeys.admin.marketing.campaign(id),
    queryFn: async (): Promise<CampaignPublic> =>
      (await AdminMarketingService.readCampaign({ path: { campaign_id: id } }))
        .data,
    refetchInterval: live ? 2_000 : false,
    refetchIntervalInBackground: false,
  })
}

export function deliveriesQuery(id: string, live: boolean) {
  return queryOptions({
    queryKey: queryKeys.admin.marketing.deliveries(id),
    queryFn: async (): Promise<DeliveriesPublic> =>
      (
        await AdminMarketingService.readDeliveries({
          path: { campaign_id: id },
          query: { limit: 500 },
        })
      ).data,
    refetchInterval: live ? 2_000 : false,
    refetchIntervalInBackground: false,
  })
}

/**
 * One place that reports and one place that invalidates.
 *
 * The same shape `adminGroups` uses: a mutation here cannot forget to refresh
 * the list it just changed, because refreshing is not its job.
 */
function useMarketingMutation<TVariables, TData>(
  run: (variables: TVariables) => Promise<TData>,
  { success, failure }: { success?: string; failure: string },
) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: run,
    onSuccess: () => {
      if (success) toast.success(success)
    },
    onError: (error: { body?: { detail?: string } } & Error) =>
      toast.error(error.body?.detail ?? error.message ?? failure),
    onSettled: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.admin.marketing.all,
      })
    },
  })
}

export function useAddContact() {
  return useMarketingMutation(
    async (body: { email: string; name: string }) =>
      (await AdminMarketingService.createContact({ body })).data,
    { success: "Contact added", failure: "That address could not be added" },
  )
}

export function useImportContacts() {
  return useMarketingMutation(
    async (file: File) =>
      (await AdminMarketingService.importContacts({ body: { file } })).data,
    { failure: "That file could not be read" },
  )
}

export function useEditContact() {
  return useMarketingMutation(
    async ({ id, ...body }: { id: string; email?: string; name?: string }) =>
      (
        await AdminMarketingService.updateContact({
          path: { contact_id: id },
          body,
        })
      ).data,
    {
      success: "Contact updated",
      failure: "That contact could not be changed",
    },
  )
}

export function useDeleteContact() {
  return useMarketingMutation(
    async (id: string) =>
      (await AdminMarketingService.deleteContact({ path: { contact_id: id } }))
        .data,
    {
      success: "Contact deleted",
      failure: "That contact could not be deleted",
    },
  )
}

export function useUnsubscribeContact() {
  return useMarketingMutation(
    async (id: string) =>
      (
        await AdminMarketingService.unsubscribeContact({
          path: { contact_id: id },
        })
      ).data,
    {
      success: "Unsubscribed",
      failure: "That contact could not be unsubscribed",
    },
  )
}

export function useCreateCampaign() {
  return useMarketingMutation(
    async (body: CampaignCreate) =>
      (await AdminMarketingService.createCampaign({ body })).data,
    { failure: "The campaign could not be started" },
  )
}

export function useCancelCampaign() {
  return useMarketingMutation(
    async (id: string) =>
      (
        await AdminMarketingService.cancelCampaign({
          path: { campaign_id: id },
        })
      ).data,
    {
      success: "Campaign stopped",
      failure: "The campaign could not be stopped",
    },
  )
}

export function usePreview() {
  return useMutation({
    mutationFn: async (body: {
      subject: string
      body_html: string
      contact_id?: string | null
    }): Promise<CampaignPreview | undefined> =>
      (await AdminMarketingService.previewCampaign({ body })).data,
    onError: (error: { body?: { detail?: string } } & Error) =>
      toast.error(error.body?.detail ?? "That message could not be rendered"),
  })
}
