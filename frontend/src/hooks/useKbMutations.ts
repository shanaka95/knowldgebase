import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"

import {
  type DocumentSummaryPublic,
  DocumentsService,
  FoldersService,
  type NamespaceTree,
} from "@/client"
import useCustomToast from "@/hooks/useCustomToast"
import { queryKeys } from "@/lib/queryKeys"
import { handleError } from "@/utils"

/** Patch a cached tree in place (optimistic rename / delete). */
function patchTree(
  queryClient: ReturnType<typeof useQueryClient>,
  namespaceId: string,
  fn: (tree: NamespaceTree) => NamespaceTree,
) {
  queryClient.setQueryData<NamespaceTree>(
    queryKeys.namespaces.tree(namespaceId),
    (old) => (old ? fn(old) : old),
  )
}

export function invalidateNamespaceViews(
  queryClient: ReturnType<typeof useQueryClient>,
  namespaceId: string,
) {
  queryClient.invalidateQueries({
    queryKey: queryKeys.namespaces.tree(namespaceId),
  })
  queryClient.invalidateQueries({ queryKey: queryKeys.namespaces.list() })
  queryClient.invalidateQueries({ queryKey: queryKeys.documents.recent() })
  queryClient.invalidateQueries({ queryKey: ["folders"] })
}

export function useCreateDocument() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const { showErrorToast } = useCustomToast()

  return useMutation({
    mutationFn: async (input: {
      namespaceId: string
      namespaceSlug: string
      folderId: string | null
      title?: string
    }) => {
      const res = await DocumentsService.createDocument({
        body: {
          namespace_id: input.namespaceId,
          folder_id: input.folderId,
          title: input.title?.trim() || "Untitled",
          content: "",
          content_format: "html",
        },
      })
      return { doc: res.data, slug: input.namespaceSlug }
    },
    onSuccess: ({ doc, slug }) => {
      invalidateNamespaceViews(queryClient, doc.namespace_id)
      navigate({
        to: "/s/$namespaceSlug/d/$documentId",
        params: { namespaceSlug: slug, documentId: doc.id },
        search: { mode: "edit" } as never,
      })
    },
    onError: handleError.bind(showErrorToast),
  })
}

export function useCreateFolder() {
  const queryClient = useQueryClient()
  const { showErrorToast, showSuccessToast } = useCustomToast()
  return useMutation({
    mutationFn: async (input: {
      namespaceId: string
      parentId: string | null
      name: string
    }) =>
      (
        await FoldersService.createFolder({
          body: {
            namespace_id: input.namespaceId,
            parent_id: input.parentId,
            name: input.name.trim(),
          },
        })
      ).data,
    onSuccess: (folder) => {
      showSuccessToast("Folder created")
      invalidateNamespaceViews(queryClient, folder.namespace_id)
    },
    onError: handleError.bind(showErrorToast),
  })
}

export function useRenameNode() {
  const queryClient = useQueryClient()
  const { showErrorToast } = useCustomToast()
  return useMutation({
    mutationFn: async (input: {
      type: "folder" | "document"
      id: string
      namespaceId: string
      name: string
    }) => {
      const name = input.name.trim()
      if (input.type === "folder") {
        await FoldersService.updateFolder({
          path: { folder_id: input.id },
          body: { name },
        })
      } else {
        await DocumentsService.updateDocument({
          path: { document_id: input.id },
          body: { title: name },
        })
      }
      return input
    },
    onMutate: async (input) => {
      const key = queryKeys.namespaces.tree(input.namespaceId)
      await queryClient.cancelQueries({ queryKey: key })
      const previous = queryClient.getQueryData<NamespaceTree>(key)
      patchTree(queryClient, input.namespaceId, (tree) => ({
        ...tree,
        folders:
          input.type === "folder"
            ? tree.folders.map((f) =>
                f.id === input.id ? { ...f, name: input.name.trim() } : f,
              )
            : tree.folders,
        documents:
          input.type === "document"
            ? tree.documents.map((d) =>
                d.id === input.id ? { ...d, title: input.name.trim() } : d,
              )
            : tree.documents,
      }))
      return { previous, key }
    },
    onError: (err, _input, ctx) => {
      if (ctx?.previous) queryClient.setQueryData(ctx.key, ctx.previous)
      handleError.call(showErrorToast, err)
    },
    onSettled: (_data, _err, input) => {
      invalidateNamespaceViews(queryClient, input.namespaceId)
      if (input.type === "document") {
        queryClient.invalidateQueries({
          queryKey: queryKeys.documents.detail(input.id),
        })
      } else {
        queryClient.invalidateQueries({
          queryKey: queryKeys.folders.detail(input.id),
        })
      }
    },
  })
}

export function useMoveNode() {
  const queryClient = useQueryClient()
  const { showErrorToast, showSuccessToast } = useCustomToast()
  return useMutation({
    mutationFn: async (input: {
      type: "folder" | "document"
      id: string
      sourceNamespaceId: string
      targetNamespaceId: string
      targetFolderId: string | null
    }) => {
      if (input.type === "folder") {
        await FoldersService.updateFolder({
          path: { folder_id: input.id },
          body: input.targetFolderId
            ? { parent_id: input.targetFolderId }
            : { move_to_root: true },
        })
      } else {
        await DocumentsService.moveDocument({
          path: { document_id: input.id },
          body: {
            namespace_id: input.targetNamespaceId,
            folder_id: input.targetFolderId,
          },
        })
      }
      return input
    },
    onSuccess: (input) => {
      showSuccessToast("Moved")
      invalidateNamespaceViews(queryClient, input.sourceNamespaceId)
      if (input.targetNamespaceId !== input.sourceNamespaceId) {
        invalidateNamespaceViews(queryClient, input.targetNamespaceId)
      }
      if (input.type === "document") {
        queryClient.invalidateQueries({
          queryKey: queryKeys.documents.detail(input.id),
        })
      }
    },
    onError: handleError.bind(showErrorToast),
  })
}

export function useDeleteNode() {
  const queryClient = useQueryClient()
  const { showErrorToast, showSuccessToast } = useCustomToast()
  return useMutation({
    mutationFn: async (input: {
      type: "folder" | "document"
      id: string
      namespaceId: string
    }) => {
      if (input.type === "folder") {
        await FoldersService.deleteFolder({ path: { folder_id: input.id } })
      } else {
        await DocumentsService.deleteDocument({
          path: { document_id: input.id },
        })
      }
      return input
    },
    onMutate: async (input) => {
      const key = queryKeys.namespaces.tree(input.namespaceId)
      await queryClient.cancelQueries({ queryKey: key })
      const previous = queryClient.getQueryData<NamespaceTree>(key)
      patchTree(queryClient, input.namespaceId, (tree) => {
        if (input.type === "document") {
          return {
            ...tree,
            documents: tree.documents.filter((d) => d.id !== input.id),
          }
        }
        // remove the folder subtree and its documents
        const removed = new Set<string>([input.id])
        let changed = true
        while (changed) {
          changed = false
          for (const f of tree.folders) {
            if (f.parent_id && removed.has(f.parent_id) && !removed.has(f.id)) {
              removed.add(f.id)
              changed = true
            }
          }
        }
        return {
          ...tree,
          folders: tree.folders.filter((f) => !removed.has(f.id)),
          documents: tree.documents.filter(
            (d) => !(d.folder_id && removed.has(d.folder_id)),
          ),
        }
      })
      return { previous, key }
    },
    onSuccess: (input) => {
      showSuccessToast(
        input.type === "folder" ? "Folder deleted" : "Page deleted",
      )
      if (input.type === "document") {
        queryClient.removeQueries({
          queryKey: queryKeys.documents.detail(input.id),
        })
      }
      queryClient.invalidateQueries({ queryKey: queryKeys.shared })
    },
    onError: (err, _input, ctx) => {
      if (ctx?.previous) queryClient.setQueryData(ctx.key, ctx.previous)
      handleError.call(showErrorToast, err)
    },
    onSettled: (_d, _e, input) =>
      invalidateNamespaceViews(queryClient, input.namespaceId),
  })
}

export type TreeDocument = DocumentSummaryPublic
