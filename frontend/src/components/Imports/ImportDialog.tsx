import { useQuery } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"
import { AlertCircle } from "lucide-react"
import { useEffect, useMemo, useState } from "react"

import { NamespaceIcon } from "@/components/Namespaces/NamespaceIcon"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { LoadingButton } from "@/components/ui/loading-button"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { useCreateImport } from "@/hooks/useImports"
import { canEditNamespace, useNamespaces } from "@/hooks/useNamespaces"
import { treeQuery } from "@/queries/namespaces"
import { FileDropzone } from "./FileDropzone"
import { filenameStem } from "./fileHelpers"

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  namespaceId?: string | null
  folderId?: string | null
}

export function ImportDialog({
  open,
  onOpenChange,
  namespaceId,
  folderId,
}: Props) {
  const { data: namespaces } = useNamespaces()
  const createImport = useCreateImport()
  const navigate = useNavigate()

  const editable = useMemo(
    () => (namespaces?.data ?? []).filter(canEditNamespace),
    [namespaces],
  )
  const [spaceId, setSpaceId] = useState(
    () => namespaceId ?? editable[0]?.id ?? "",
  )
  const [folder, setFolder] = useState<string | null>(folderId ?? null)
  const [file, setFile] = useState<File | null>(null)
  const [title, setTitle] = useState("")
  const [titleTouched, setTitleTouched] = useState(false)
  const [prompt, setPrompt] = useState("")
  const [rejection, setRejection] = useState<string | null>(null)

  /*
   * The spaces list is usually still loading on the first render, so the
   * initial state above falls back to "" and the dialog would stay
   * unsubmittable. Adopt the first editable space as soon as one is known,
   * without overriding a choice the user has already made.
   */
  useEffect(() => {
    if (!spaceId && editable.length > 0) setSpaceId(editable[0].id)
  }, [spaceId, editable])

  const { data: tree } = useQuery({ ...treeQuery(spaceId), enabled: !!spaceId })
  const folders = tree?.raw.folders ?? []

  const chooseFile = (next: File | null) => {
    setFile(next)
    setRejection(null)
    // the filename is a good default title until the user edits it themselves
    if (next && !titleTouched) setTitle(filenameStem(next.name))
    if (!next && !titleTouched) setTitle("")
  }

  const submit = () => {
    if (!file || !spaceId) return
    createImport.mutate(
      {
        file,
        namespaceId: spaceId,
        folderId: folder,
        title,
        prompt,
      },
      {
        onSuccess: () => {
          onOpenChange(false)
          void navigate({ to: "/imports" })
        },
      },
    )
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg" data-testid="import-dialog">
        <DialogHeader>
          <DialogTitle>Import a PDF or image</DialogTitle>
          <DialogDescription>
            The file is read by a document model and becomes an editable page.
            The original stays attached to it.
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-4">
          <FileDropzone
            file={file}
            onFile={chooseFile}
            onReject={setRejection}
            disabled={createImport.isPending}
          />
          {rejection && (
            <Alert variant="destructive" data-testid="import-rejection">
              <AlertCircle />
              <AlertDescription>{rejection}</AlertDescription>
            </Alert>
          )}

          <div className="flex flex-col gap-2">
            <Label htmlFor="import-title">Page title</Label>
            <Input
              id="import-title"
              value={title}
              placeholder="Taken from the file name"
              disabled={createImport.isPending}
              onChange={(e) => {
                setTitle(e.target.value)
                setTitleTouched(true)
              }}
              data-testid="import-title"
            />
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <div className="flex flex-col gap-2">
              <Label htmlFor="import-space">Space</Label>
              <Select
                value={spaceId}
                onValueChange={(v) => {
                  setSpaceId(v)
                  setFolder(null)
                }}
                disabled={createImport.isPending}
              >
                <SelectTrigger
                  id="import-space"
                  className="w-full"
                  data-testid="import-space-select"
                >
                  <SelectValue placeholder="Select a space" />
                </SelectTrigger>
                <SelectContent>
                  {editable.map((ns) => (
                    <SelectItem key={ns.id} value={ns.id}>
                      <span className="flex items-center gap-2">
                        <NamespaceIcon
                          icon={ns.icon}
                          color={ns.color}
                          size="xs"
                        />
                        {ns.name}
                      </span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="import-folder">Folder</Label>
              <Select
                value={folder ?? "__root__"}
                onValueChange={(v) => setFolder(v === "__root__" ? null : v)}
                disabled={createImport.isPending}
              >
                <SelectTrigger
                  id="import-folder"
                  className="w-full"
                  data-testid="import-folder-select"
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__root__">Space root</SelectItem>
                  {folders.map((f) => (
                    <SelectItem key={f.id} value={f.id}>
                      {f.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="flex flex-col gap-2">
            <Label htmlFor="import-prompt">
              Parsing hint{" "}
              <span className="font-normal text-muted-foreground">
                (optional)
              </span>
            </Label>
            <Textarea
              id="import-prompt"
              rows={2}
              value={prompt}
              disabled={createImport.isPending}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder="Only used if the document model is unavailable and a general model transcribes the pages instead. Usually leave this empty."
              data-testid="import-prompt"
            />
          </div>
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={createImport.isPending}
          >
            Cancel
          </Button>
          <LoadingButton
            onClick={submit}
            disabled={!file || !spaceId}
            loading={createImport.isPending}
            data-testid="import-submit"
          >
            Import
          </LoadingButton>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
