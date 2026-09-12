import { useQuery } from "@tanstack/react-query"

import { NameDialog } from "@/components/Folders/NameDialog"
import { ImportDialog } from "@/components/Imports/ImportDialog"
import { DeleteNamespaceDialog } from "@/components/Namespaces/DeleteNamespaceDialog"
import { NamespaceFormDialog } from "@/components/Namespaces/NamespaceFormDialog"
import {
  useCreateDocument,
  useCreateFolder,
  useRenameNode,
} from "@/hooks/useKbMutations"
import { namespaceQuery } from "@/queries/namespaces"
import { type DialogRequest, useDialogStore } from "@/stores/dialogs"
import { DeleteDialog } from "./DeleteDialog"
import { MoveDialog } from "./MoveDialog"
import { ShareDialog } from "./ShareDialog"

function EditNamespace({
  request,
  onClose,
}: {
  request: Extract<DialogRequest, { kind: "editNamespace" }>
  onClose: () => void
}) {
  const { data } = useQuery(namespaceQuery(request.target.id))
  if (!data) return null
  return (
    <NamespaceFormDialog
      open
      onOpenChange={(o) => !o && onClose()}
      namespace={data}
    />
  )
}

function Dialogs({
  request,
  onClose,
}: {
  request: DialogRequest
  onClose: () => void
}) {
  const createFolder = useCreateFolder()
  const createDocument = useCreateDocument()
  const rename = useRenameNode()
  const close = (open: boolean) => !open && onClose()

  switch (request.kind) {
    case "createNamespace":
      return <NamespaceFormDialog open onOpenChange={close} />
    case "editNamespace":
      return <EditNamespace request={request} onClose={onClose} />
    case "deleteNamespace":
      return (
        <DeleteNamespaceDialog
          open
          onOpenChange={close}
          namespace={request.target}
        />
      )
    case "newFolder":
      return (
        <NameDialog
          open
          onOpenChange={close}
          title="New folder"
          label="Folder name"
          placeholder="e.g. Meeting notes"
          submitLabel="Create folder"
          loading={createFolder.isPending}
          testId="new-folder-dialog"
          onSubmit={(name) =>
            createFolder.mutate(
              {
                namespaceId: request.namespaceId,
                parentId: request.parentId,
                name,
              },
              { onSuccess: onClose },
            )
          }
        />
      )
    case "newDocument":
      return (
        <NameDialog
          open
          onOpenChange={close}
          title="New page"
          label="Title"
          placeholder="Untitled"
          submitLabel="Create page"
          loading={createDocument.isPending}
          testId="new-document-dialog"
          onSubmit={(title) =>
            createDocument.mutate(
              {
                namespaceId: request.namespaceId,
                namespaceSlug: request.namespaceSlug,
                folderId: request.folderId,
                title,
              },
              { onSuccess: onClose },
            )
          }
        />
      )
    case "rename": {
      const isFolder = request.target.type === "folder"
      const current =
        request.target.type === "folder"
          ? request.target.name
          : request.target.title
      return (
        <NameDialog
          open
          onOpenChange={close}
          title={isFolder ? "Rename folder" : "Rename page"}
          label={isFolder ? "Folder name" : "Title"}
          submitLabel="Rename"
          initialValue={current}
          loading={rename.isPending}
          testId="rename-dialog"
          onSubmit={(name) =>
            rename.mutate(
              {
                type: request.target.type,
                id: request.target.id,
                namespaceId: request.target.namespaceId,
                name,
              },
              { onSuccess: onClose },
            )
          }
        />
      )
    }
    case "move":
      return <MoveDialog open onOpenChange={close} target={request.target} />
    case "delete":
      return <DeleteDialog open onOpenChange={close} target={request.target} />
    case "share":
      return <ShareDialog open onOpenChange={close} target={request.target} />
    case "import":
      return (
        <ImportDialog
          open
          onOpenChange={close}
          namespaceId={request.namespaceId}
          folderId={request.folderId}
        />
      )
    default:
      return null
  }
}

/** Mounted once in the authenticated layout; renders whichever dialog was requested. */
export function GlobalDialogs() {
  const current = useDialogStore((s) => s.current)
  const close = useDialogStore((s) => s.close)
  if (!current) return null
  // key forces a remount (fresh form state) when a different request arrives
  return (
    <Dialogs key={JSON.stringify(current)} request={current} onClose={close} />
  )
}
