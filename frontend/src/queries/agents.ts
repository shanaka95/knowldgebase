import { queryOptions } from "@tanstack/react-query"

import { AdminChannelsService, AgentsService } from "@/client"

export const agentKeys = {
  all: ["agents"] as const,
  list: () => ["agents", "list"] as const,
  detail: (id: string) => ["agents", id] as const,
  channels: (id: string) => ["agents", id, "channels"] as const,
  adminChannels: () => ["admin", "channels"] as const,
}

export function agentsQuery() {
  return queryOptions({
    queryKey: agentKeys.list(),
    queryFn: async () => (await AgentsService.readAgents()).data,
  })
}

/**
 * Polls while a link is outstanding.
 *
 * The connection appears only once the person has sent the code from their
 * messaging app, which happens on another device entirely - so the page has to
 * notice on its own rather than wait for something to click.
 */
export function agentQuery(agentId: string, options?: { poll?: boolean }) {
  return queryOptions({
    queryKey: agentKeys.detail(agentId),
    queryFn: async () =>
      (await AgentsService.readAgent({ path: { agent_id: agentId } })).data,
    refetchInterval: options?.poll ? 3_000 : false,
    refetchIntervalInBackground: false,
  })
}

export function agentChannelsQuery(agentId: string) {
  return queryOptions({
    queryKey: agentKeys.channels(agentId),
    queryFn: async () =>
      (await AgentsService.readAgentChannels({ path: { agent_id: agentId } }))
        .data,
  })
}

export function adminChannelsQuery() {
  return queryOptions({
    queryKey: agentKeys.adminChannels(),
    queryFn: async () => (await AdminChannelsService.readChannels()).data,
  })
}

/** Display names, kept in one place so the two pages cannot disagree. */
export const CHANNEL_LABELS: Record<string, string> = {
  whatsapp: "WhatsApp",
  telegram: "Telegram",
  slack: "Slack",
  discord: "Discord",
}

export function channelLabel(channel: string): string {
  return CHANNEL_LABELS[channel] ?? channel
}
