import {
  type InfiniteData,
  infiniteQueryOptions,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query"

import {
  type AskConversationDetail,
  type AskConversationPublic,
  type AskConversationsPublic,
  AskService,
} from "@/client"
import { queryKeys } from "@/lib/queryKeys"

/** How many threads the rail asks for at a time. */
export const CONVERSATIONS_PAGE_SIZE = 30

/**
 * The history rail.
 *
 * Paged rather than fetched whole: a heavy user accumulates hundreds of
 * threads, and the rail only ever shows a screenful. Each row is a title and a
 * timestamp, so a page is a couple of kilobytes.
 */
export function conversationsQuery() {
  return infiniteQueryOptions({
    queryKey: queryKeys.askConversations.list(),
    queryFn: async ({ pageParam }): Promise<AskConversationsPublic> =>
      (
        await AskService.readConversations({
          query: { limit: CONVERSATIONS_PAGE_SIZE, offset: pageParam },
        })
      ).data,
    initialPageParam: 0,
    getNextPageParam: (last, pages) => {
      const loaded = pages.reduce((n, page) => n + page.data.length, 0)
      return loaded < last.count ? loaded : undefined
    },
    staleTime: 30_000,
  })
}

/** One thread with its messages — fetched only when a thread is opened. */
export function conversationQuery(conversationId: string) {
  return {
    queryKey: queryKeys.askConversations.detail(conversationId),
    queryFn: async (): Promise<AskConversationDetail> =>
      (
        await AskService.readConversation({
          path: { conversation_id: conversationId },
        })
      ).data,
    staleTime: 60_000,
  }
}

type ListData = InfiniteData<AskConversationsPublic>

export function useRenameConversation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, title }: { id: string; title: string }) =>
      (
        await AskService.renameConversation({
          path: { conversation_id: id },
          body: { title },
        })
      ).data,
    // Renaming is a rail-local edit; showing it immediately and reconciling
    // afterwards beats a spinner on a title the user just typed.
    onMutate: async ({ id, title }) => {
      await queryClient.cancelQueries({
        queryKey: queryKeys.askConversations.list(),
      })
      const previous = queryClient.getQueryData<ListData>(
        queryKeys.askConversations.list(),
      )
      queryClient.setQueryData<ListData>(
        queryKeys.askConversations.list(),
        (old) =>
          old && {
            ...old,
            pages: old.pages.map((page) => ({
              ...page,
              data: page.data.map((c) => (c.id === id ? { ...c, title } : c)),
            })),
          },
      )
      return { previous }
    },
    onError: (_error, _variables, context) => {
      if (context?.previous) {
        queryClient.setQueryData(
          queryKeys.askConversations.list(),
          context.previous,
        )
      }
    },
    onSettled: (_data, _error, { id }) => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.askConversations.list(),
      })
      void queryClient.invalidateQueries({
        queryKey: queryKeys.askConversations.detail(id),
      })
    },
  })
}

export function useDeleteConversation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (id: string) => {
      await AskService.removeConversation({ path: { conversation_id: id } })
      return id
    },
    onMutate: async (id) => {
      await queryClient.cancelQueries({
        queryKey: queryKeys.askConversations.list(),
      })
      const previous = queryClient.getQueryData<ListData>(
        queryKeys.askConversations.list(),
      )
      queryClient.setQueryData<ListData>(
        queryKeys.askConversations.list(),
        (old) =>
          old && {
            ...old,
            pages: old.pages.map((page) => ({
              ...page,
              count: Math.max(0, page.count - 1),
              data: page.data.filter((c) => c.id !== id),
            })),
          },
      )
      return { previous }
    },
    onError: (_error, _id, context) => {
      if (context?.previous) {
        queryClient.setQueryData(
          queryKeys.askConversations.list(),
          context.previous,
        )
      }
    },
    onSuccess: (id) => {
      queryClient.removeQueries({
        queryKey: queryKeys.askConversations.detail(id),
      })
    },
    onSettled: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.askConversations.list(),
      })
    },
  })
}

export type { AskConversationDetail, AskConversationPublic }
