import { create } from "zustand"

/**
 * Global dialog bus. Feature code opens dialogs from anywhere (tree context menu,
 * document "…" menu, command palette) and a single <GlobalDialogs /> mounted in the
 * layout renders them. Keeps dialogs out of every tree node.
 */
export type DialogTarget =
  | { type: "namespace"; id: string; slug: string; name: string }
  | {
      type: "folder"
      id: string
      namespaceId: string
      namespaceSlug: string
      name: string
      parentId: string | null
    }
  | {
      type: "document"
      id: string
      namespaceId: string
      namespaceSlug: string
      title: string
      folderId: string | null
    }

export type DialogRequest =
  | { kind: "createNamespace" }
  | {
      kind: "editNamespace"
      target: Extract<DialogTarget, { type: "namespace" }>
    }
  | {
      kind: "deleteNamespace"
      target: Extract<DialogTarget, { type: "namespace" }>
    }
  | {
      kind: "newFolder"
      namespaceId: string
      namespaceSlug: string
      parentId: string | null
    }
  | {
      kind: "newDocument"
      namespaceId: string
      namespaceSlug: string
      folderId: string | null
    }
  | {
      kind: "rename"
      target: Extract<DialogTarget, { type: "folder" | "document" }>
    }
  | {
      kind: "move"
      target: Extract<DialogTarget, { type: "folder" | "document" }>
    }
  | {
      kind: "delete"
      target: Extract<DialogTarget, { type: "folder" | "document" }>
    }
  | {
      kind: "share"
      target: Extract<DialogTarget, { type: "document" | "namespace" }>
    }
  | {
      kind: "import"
      /** Prefills the pickers; omitted when opened from a global action. */
      namespaceId?: string | null
      namespaceSlug?: string | null
      folderId?: string | null
    }

interface DialogState {
  current: DialogRequest | null
  open: (request: DialogRequest) => void
  close: () => void
}

export const useDialogStore = create<DialogState>((set) => ({
  current: null,
  open: (request) => set({ current: request }),
  close: () => set({ current: null }),
}))

export const openDialog = (request: DialogRequest) =>
  useDialogStore.getState().open(request)
