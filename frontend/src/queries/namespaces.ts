import { queryOptions } from "@tanstack/react-query"

import {
  type DocumentSummaryPublic,
  type FolderPublic,
  NamespacesService,
  type NamespaceTree,
} from "@/client"
import { queryKeys } from "@/lib/queryKeys"

export function namespacesQuery() {
  return queryOptions({
    queryKey: queryKeys.namespaces.list(),
    queryFn: async () => (await NamespacesService.readNamespaces()).data,
    staleTime: 30_000,
  })
}

export function namespaceBySlugQuery(slug: string) {
  return queryOptions({
    queryKey: queryKeys.namespaces.bySlug(slug),
    queryFn: async () =>
      (await NamespacesService.readNamespaceBySlug({ path: { slug } })).data,
  })
}

export function namespaceQuery(namespaceId: string) {
  return queryOptions({
    queryKey: queryKeys.namespaces.detail(namespaceId),
    queryFn: async () =>
      (
        await NamespacesService.readNamespace({
          path: { namespace_id: namespaceId },
        })
      ).data,
  })
}

export function namespaceMembersQuery(namespaceId: string) {
  return queryOptions({
    queryKey: queryKeys.namespaces.members(namespaceId),
    queryFn: async () =>
      (
        await NamespacesService.readNamespaceMembers({
          path: { namespace_id: namespaceId },
        })
      ).data,
  })
}

/** Normalised view of a namespace tree for fast lookups in the sidebar and dialogs. */
export interface TreeIndex {
  raw: NamespaceTree
  foldersById: Map<string, FolderPublic>
  documentsById: Map<string, DocumentSummaryPublic>
  childrenOf: (parentId: string | null) => FolderPublic[]
  docsOf: (folderId: string | null) => DocumentSummaryPublic[]
  /** Ancestors (root → …) of a folder, inclusive of the folder itself. */
  pathTo: (folderId: string | null) => FolderPublic[]
  /** Ids of a folder and every folder below it. */
  descendantIds: (folderId: string) => Set<string>
}

const byName = <T extends { name?: string; title?: string }>(a: T, b: T) =>
  (a.name ?? a.title ?? "").localeCompare(b.name ?? b.title ?? "", undefined, {
    sensitivity: "base",
    numeric: true,
  })

export function indexTree(raw: NamespaceTree): TreeIndex {
  const foldersById = new Map<string, FolderPublic>()
  const documentsById = new Map<string, DocumentSummaryPublic>()
  const folderChildren = new Map<string | null, FolderPublic[]>()
  const folderDocs = new Map<string | null, DocumentSummaryPublic[]>()

  for (const f of raw.folders) {
    foldersById.set(f.id, f)
    const key = f.parent_id ?? null
    const list = folderChildren.get(key) ?? []
    list.push(f)
    folderChildren.set(key, list)
  }
  for (const d of raw.documents) {
    documentsById.set(d.id, d)
    const key = d.folder_id ?? null
    const list = folderDocs.get(key) ?? []
    list.push(d)
    folderDocs.set(key, list)
  }
  for (const list of folderChildren.values()) list.sort(byName)
  for (const list of folderDocs.values()) list.sort(byName)

  const pathTo = (folderId: string | null): FolderPublic[] => {
    const path: FolderPublic[] = []
    let current = folderId ? foldersById.get(folderId) : undefined
    const seen = new Set<string>()
    while (current && !seen.has(current.id)) {
      seen.add(current.id)
      path.unshift(current)
      current = current.parent_id
        ? foldersById.get(current.parent_id)
        : undefined
    }
    return path
  }

  const descendantIds = (folderId: string): Set<string> => {
    const out = new Set<string>([folderId])
    const stack = [folderId]
    while (stack.length) {
      const id = stack.pop() as string
      for (const child of folderChildren.get(id) ?? []) {
        if (!out.has(child.id)) {
          out.add(child.id)
          stack.push(child.id)
        }
      }
    }
    return out
  }

  return {
    raw,
    foldersById,
    documentsById,
    childrenOf: (parentId) => folderChildren.get(parentId ?? null) ?? [],
    docsOf: (folderId) => folderDocs.get(folderId ?? null) ?? [],
    pathTo,
    descendantIds,
  }
}

export function treeQuery(namespaceId: string) {
  return queryOptions({
    queryKey: queryKeys.namespaces.tree(namespaceId),
    queryFn: async () =>
      (
        await NamespacesService.readNamespaceTree({
          path: { namespace_id: namespaceId },
        })
      ).data,
    select: indexTree,
    staleTime: 15_000,
  })
}
