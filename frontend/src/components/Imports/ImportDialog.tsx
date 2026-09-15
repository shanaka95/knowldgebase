import { useNavigate } from "@tanstack/react-router"
import { AlertCircle, HardDrive, Upload } from "lucide-react"
import { useEffect, useMemo, useState } from "react"
import { DestinationFields } from "@/components/Imports/DestinationFields"
import {
  DriveNotConnected,
  DrivePicker,
  useDriveConnected,
} from "@/components/Imports/DrivePicker"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
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
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Textarea } from "@/components/ui/textarea"
import type { PickedFile } from "@/hooks/useGooglePicker"
import { useCreateImport, useImportFromDrive } from "@/hooks/useImports"
import { canEditNamespace, useNamespaces } from "@/hooks/useNamespaces"
import { FileDropzone } from "./FileDropzone"

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
  const [files, setFiles] = useState<File[]>([])
  const [driveFiles, setDriveFiles] = useState<PickedFile[]>([])
  // Which source the dialog is showing. Drive is offered only where it is
  // actually reachable, so nobody is sent down a path that ends in a wall.
  const [source, setSource] = useState<"device" | "drive">("device")
  const drive = useDriveConnected()
  const [title, setTitle] = useState("")
  /**
   * On by default, because the model reads the document's own opening heading
   * and that names the page better than a filename like "scan_0007.pdf" ever
   * will. Unticking it hands the decision back.
   */
  const [autoTitle, setAutoTitle] = useState(true)
  const [combine, setCombine] = useState(false)
  const [prompt, setPrompt] = useState("")
  const [note, setNote] = useState("")
  const [rejection, setRejection] = useState<string | null>(null)

  const many = files.length > 1
  /**
   * Several files becoming several pages cannot share one title: that would
   * produce a list of pages with identical names. Combining them into a single
   * page makes a title meaningful again.
   */
  const titleAvailable = !many || combine

  /*
   * The spaces list is usually still loading on the first render, so the
   * initial state above falls back to "" and the dialog would stay
   * unsubmittable. Adopt the first editable space as soon as one is known,
   * without overriding a choice the user has already made.
   */
  useEffect(() => {
    if (!spaceId && editable.length > 0) setSpaceId(editable[0].id)
  }, [spaceId, editable])

  const importFromDrive = useImportFromDrive()

  const chooseFiles = (next: File[]) => {
    setFiles(next)
    setRejection(null)
  }

  const busy = createImport.isPending || importFromDrive.isPending
  const chosen = source === "drive" ? driveFiles.length : files.length

  const submit = () => {
    if (chosen === 0 || !spaceId) return
    if (source === "drive") {
      importFromDrive.mutate(
        {
          files: driveFiles,
          namespaceId: spaceId,
          folderId: folder,
          note,
        },
        {
          onSuccess: () => {
            onOpenChange(false)
            void navigate({ to: "/imports" })
          },
        },
      )
      return
    }
    createImport.mutate(
      {
        files,
        namespaceId: spaceId,
        folderId: folder,
        // An empty title is the instruction to derive one, so a manual title is
        // sent only when it is both wanted and possible.
        title: autoTitle || !titleAvailable ? null : title,
        prompt,
        note,
        combine: many && combine,
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
          <DialogTitle>Upload a document</DialogTitle>
          <DialogDescription>
            {source === "drive"
              ? "Pick files in Google's own chooser. Each is read by a document model and becomes an editable page, with the original attached."
              : "Choose a file or photograph one. Each is read by a document model and becomes an editable page, with the original attached."}
          </DialogDescription>
        </DialogHeader>

        {/*
          The dialog body is a grid item, so without min-w-0 a long file name
          in the preview or the rejection message would widen the track and
          push the controls outside the dialog box.
        */}
        <div className="flex min-w-0 flex-col gap-4">
          {/* Offered only when a Drive is actually connectable here: a tab
              that leads nowhere is worse than no tab. */}
          {drive.available && (
            <Tabs
              value={source}
              onValueChange={(v) => setSource(v as "device" | "drive")}
            >
              <TabsList className="w-full">
                <TabsTrigger
                  value="device"
                  className="flex-1"
                  data-testid="source-device"
                >
                  <Upload />
                  From this device
                </TabsTrigger>
                <TabsTrigger
                  value="drive"
                  className="flex-1"
                  data-testid="source-drive"
                >
                  <HardDrive />
                  Google Drive
                </TabsTrigger>
              </TabsList>
            </Tabs>
          )}

          {source === "drive" ? (
            drive.connected ? (
              <DrivePicker
                files={driveFiles}
                onChange={setDriveFiles}
                disabled={busy}
              />
            ) : (
              <DriveNotConnected onLeave={() => onOpenChange(false)} />
            )
          ) : (
            <FileDropzone
              files={files}
              onFiles={chooseFiles}
              onReject={setRejection}
              disabled={busy}
            />
          )}

          {source === "device" && many && (
            <div className="flex items-start gap-3 rounded-lg border bg-muted/20 p-3">
              <Checkbox
                id="import-combine"
                checked={combine}
                disabled={busy}
                onCheckedChange={(v) => setCombine(v === true)}
                className="mt-0.5"
                data-testid="import-combine"
              />
              <div className="grid min-w-0 gap-1">
                <Label htmlFor="import-combine" className="font-medium">
                  Combine into a single page
                </Label>
                <p className="text-muted-foreground text-xs">
                  {combine
                    ? `All ${files.length} files become one page, in the order listed above.`
                    : `Each file becomes its own page. Tick this if they are parts of one document.`}
                </p>
              </div>
            </div>
          )}
          {rejection && (
            <Alert variant="destructive" data-testid="import-rejection">
              <AlertCircle />
              <AlertDescription className="break-all">
                {rejection}
              </AlertDescription>
            </Alert>
          )}

          <div className="flex flex-col gap-2" hidden={source === "drive"}>
            <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
              <Label htmlFor="import-title">Page title</Label>
              <div className="flex items-center gap-2">
                <Checkbox
                  id="import-auto-title"
                  checked={autoTitle || !titleAvailable}
                  disabled={busy || !titleAvailable}
                  onCheckedChange={(v) => setAutoTitle(v === true)}
                  data-testid="import-auto-title"
                />
                <Label
                  htmlFor="import-auto-title"
                  className="font-normal text-muted-foreground text-xs"
                >
                  Generate it from the document
                </Label>
              </div>
            </div>
            <Input
              id="import-title"
              value={autoTitle || !titleAvailable ? "" : title}
              placeholder={
                titleAvailable
                  ? "Taken from the document's own heading"
                  : "Each page is named after its own heading"
              }
              disabled={busy || autoTitle || !titleAvailable}
              onChange={(e) => setTitle(e.target.value)}
              data-testid="import-title"
            />
            {!titleAvailable && (
              <p className="text-muted-foreground text-xs">
                Several files are becoming separate pages, so each is named
                after its own content.
              </p>
            )}
          </div>

          <DestinationFields
            spaces={editable}
            spaceId={spaceId}
            onSpaceChange={setSpaceId}
            folderId={folder}
            onFolderChange={setFolder}
            disabled={busy}
            idPrefix="import"
          />

          <div className="flex flex-col gap-2">
            <Label htmlFor="import-note">
              Notes{" "}
              <span className="font-normal text-muted-foreground">
                (optional)
              </span>
            </Label>
            <Textarea
              id="import-note"
              rows={3}
              value={note}
              disabled={busy}
              onChange={(e) => setNote(e.target.value)}
              placeholder="Anything you want to add to this document — why you are keeping it, what it replaces, what to watch out for. Saved with the page and searchable alongside it."
              data-testid="import-note"
            />
            <p className="text-muted-foreground text-xs">
              {many && !combine
                ? "Added to every page this upload creates."
                : "Added to the page as its first note."}
            </p>
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
              disabled={busy}
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
            disabled={busy}
          >
            Cancel
          </Button>
          <LoadingButton
            onClick={submit}
            disabled={chosen === 0 || !spaceId}
            loading={busy}
            data-testid="import-submit"
          >
            Import
          </LoadingButton>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
