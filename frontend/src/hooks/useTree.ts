import { useQuery } from "@tanstack/react-query"
import { create } from "zustand"
import { persist } from "zustand/middleware"

import { treeQuery } from "@/queries/namespaces"

export function useTree(namespaceId: string | null | undefined) {
  return useQuery({
    ...treeQuery(namespaceId ?? ""),
    enabled: Boolean(namespaceId),
  })
}

interface TreeState {
  /** namespaceId → expanded folder ids */
  expanded: Record<string, string[]>
  renamingId: string | null
  isExpanded: (namespaceId: string, folderId: string) => boolean
  toggle: (namespaceId: string, folderId: string) => void
  setExpanded: (namespaceId: string, folderId: string, open: boolean) => void
  expandMany: (namespaceId: string, folderIds: string[]) => void
  setRenaming: (id: string | null) => void
}

export const useTreeStore = create<TreeState>()(
  persist(
    (set, get) => ({
      expanded: {},
      renamingId: null,
      isExpanded: (ns, id) => (get().expanded[ns] ?? []).includes(id),
      toggle: (ns, id) => {
        const current = get().expanded[ns] ?? []
        const next = current.includes(id)
          ? current.filter((x) => x !== id)
          : [...current, id]
        set({ expanded: { ...get().expanded, [ns]: next } })
      },
      setExpanded: (ns, id, open) => {
        const current = get().expanded[ns] ?? []
        const has = current.includes(id)
        if (open === has) return
        set({
          expanded: {
            ...get().expanded,
            [ns]: open ? [...current, id] : current.filter((x) => x !== id),
          },
        })
      },
      expandMany: (ns, ids) => {
        const current = get().expanded[ns] ?? []
        const missing = ids.filter((id) => !current.includes(id))
        if (missing.length === 0) return
        set({ expanded: { ...get().expanded, [ns]: [...current, ...missing] } })
      },
      setRenaming: (renamingId) => set({ renamingId }),
    }),
    {
      name: "kb:tree",
      partialize: (state) => ({ expanded: state.expanded }),
    },
  ),
)
