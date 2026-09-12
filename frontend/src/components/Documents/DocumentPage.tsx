import { useQueryClient } from "@tanstack/react-query"
import { useBlocker, useMatches } from "@tanstack/react-router"
import { ListTree } from "lucide-react"
import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react"

import {
  AttachmentsService,
  type DocumentPublic,
  DocumentsService,
  type DocumentUpdate,
  type FolderPublic,
  type NamespacePublic,
  type NamespaceTree,
} from "@/client"
import { Editor } from "@/components/Editor/Editor"
import { EditorToolbar } from "@/components/Editor/EditorToolbar"
import { TableOfContents, useToc } from "@/components/Editor/TableOfContents"
import { usePendingUploads } from "@/components/Editor/upload"
import { useDocumentEditor } from "@/components/Editor/useDocumentEditor"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Button } from "@/components/ui/button"
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { Skeleton } from "@/components/ui/skeleton"
import { useAttachmentBlobFetcher } from "@/hooks/useAttachmentBlob"
import { useAutosave } from "@/hooks/useAutosave"
import { useDocument, useDocumentPolling } from "@/hooks/useDocument"
import { useEmbeddingStatus } from "@/hooks/useEmbeddingStatus"
import { useIsMobile } from "@/hooks/useMobile"
import { type Crumb, useCrumbsStore } from "@/lib/breadcrumbs"
import { queryKeys } from "@/lib/queryKeys"
import { cn } from "@/lib/utils"
import { ConflictBanner } from "./ConflictBanner"
import { DocumentHeader } from "./DocumentHeader"
import { NewVersionChip } from "./NewVersionChip"
import { SourceFileCard, SourceFileChip } from "./SourceFileCard"

const AiIndexPanel = lazy(() => import("@/components/Embeddings/AiIndexPanel"))

export type DocumentMode = "view" | "edit"
export type DocumentPanel = "ai" | "toc" | undefined

interface DocumentPageProps {
  documentId: string
  namespaceSlug: string
  mode: DocumentMode
  panel: DocumentPanel
  onChangeSearch: (patch: {
    mode?: DocumentMode
    panel?: DocumentPanel
  }) => void
}

type SavePayload = Pick<
  DocumentUpdate,
  "title" | "content" | "content_format" | "doc_type"
>

function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  if (target.isContentEditable) return true
  const tag = target.tagName
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT"
}

/** Folder ancestors (root → leaf) for a folder id, from the cached namespace tree. */
function folderPath(
  folders: FolderPublic[],
  folderId: string | null,
): FolderPublic[] {
  const byId = new Map(folders.map((f) => [f.id, f]))
  const path: FolderPublic[] = []
  let current = folderId ? byId.get(folderId) : undefined
  let guard = 0
  while (current && guard < 50) {
    path.unshift(current)
    current = current.parent_id ? byId.get(current.parent_id) : undefined
    guard += 1
  }
  return path
}

export function DocumentPage({
  documentId,
  namespaceSlug,
  mode: requestedMode,
  panel,
  onChangeSearch,
}: DocumentPageProps) {
  const queryClient = useQueryClient()
  const isMobile = useIsMobile()
  const { data: document } = useDocument(documentId)
  const canEdit = document.my_role === "editor"
  const mode: DocumentMode =
    requestedMode === "edit" && canEdit ? "edit" : "view"
  const editing = mode === "edit"

  // ---- local editing state ---------------------------------------------------
  const [title, setTitle] = useState(document.title)
  const titleRef = useRef(document.title)
  const htmlRef = useRef(document.content_html)
  const [docType, setDocType] = useState<string | null>(
    document.doc_type ?? null,
  )
  const docTypeRef = useRef<string | null>(document.doc_type ?? null)
  /** The type the server last confirmed, to spot a newly invented one. */
  const savedDocTypeRef = useRef<string | null>(document.doc_type ?? null)
  /** Version the editor's current content was loaded from. */
  const [loadedVersion, setLoadedVersion] = useState(document.version)
  const [finishing, setFinishing] = useState(false)

  const setTitleBoth = useCallback((value: string) => {
    titleRef.current = value
    setTitle(value)
  }, [])

  const setDocTypeBoth = useCallback((value: string | null) => {
    docTypeRef.current = value
    setDocType(value)
  }, [])

  // ---- editor ----------------------------------------------------------------
  const fetchAttachmentBlob = useAttachmentBlobFetcher()
  const uploadImage = useCallback(
    async (file: File) => {
      const response = await AttachmentsService.uploadAttachment({
        body: {
          file,
          namespace_id: document.namespace_id,
          document_id: document.id,
        },
      })
      return { id: response.data.id, url: response.data.download_url }
    },
    [document.id, document.namespace_id],
  )

  const autosaveRef = useRef<ReturnType<
    typeof useAutosave<SavePayload>
  > | null>(null)

  const editor = useDocumentEditor({
    content: document.content_html,
    editable: editing,
    uploadImage: canEdit ? uploadImage : null,
    fetchAttachmentBlob,
    onUpdate: (html) => {
      htmlRef.current = html
      autosaveRef.current?.markDirty()
    },
  })

  // ---- autosave --------------------------------------------------------------
  const autosave = useAutosave<SavePayload>({
    baseVersion: loadedVersion,
    enabled: editing,
    isBlocked: () => usePendingUploads.getState().count > 0,
    getPayload: () => ({
      title: titleRef.current.trim() || "Untitled",
      content: htmlRef.current,
      content_format: "html",
      // "" clears the type; the server treats it as metadata, so sending it on
      // every save never bumps the version or re-runs the AI index.
      doc_type: docTypeRef.current ?? "",
    }),
    save: async (payload, base) => {
      const response = await DocumentsService.updateDocument({
        path: { document_id: documentId },
        body: { ...payload, expected_version: base },
      })
      const fresh = response.data
      queryClient.setQueryData<DocumentPublic>(
        queryKeys.documents.detail(documentId),
        (prev) => (prev ? { ...prev, ...fresh } : fresh),
      )
      setLoadedVersion(fresh.version)
      if ((fresh.doc_type ?? null) !== savedDocTypeRef.current) {
        savedDocTypeRef.current = fresh.doc_type ?? null
        // A type only exists once a page uses it, so the suggestions changed.
        void queryClient.invalidateQueries({
          queryKey: queryKeys.documents.types(),
        })
      }
      void queryClient.invalidateQueries({
        queryKey: queryKeys.documents.embeddings(documentId),
      })
      void queryClient.invalidateQueries({
        queryKey: queryKeys.namespaces.tree(document.namespace_id),
      })
      void queryClient.invalidateQueries({
        queryKey: queryKeys.documents.recent(),
      })
      return { version: fresh.version }
    },
    onReload: async () => {
      const fresh = await queryClient.fetchQuery({
        queryKey: queryKeys.documents.detail(documentId),
        queryFn: async () =>
          (
            await DocumentsService.readDocument({
              path: { document_id: documentId },
            })
          ).data,
        staleTime: 0,
      })
      htmlRef.current = fresh.content_html
      setTitleBoth(fresh.title)
      setDocTypeBoth(fresh.doc_type ?? null)
      savedDocTypeRef.current = fresh.doc_type ?? null
      editor?.commands.setContent(fresh.content_html, { emitUpdate: false })
      setLoadedVersion(fresh.version)
    },
  })
  autosaveRef.current = autosave

  const onTitleChange = useCallback(
    (value: string) => {
      setTitleBoth(value)
      autosave.markDirty()
    },
    [autosave, setTitleBoth],
  )

  const onDocTypeChange = useCallback(
    (value: string | null) => {
      setDocTypeBoth(value)
      autosave.markDirty()
    },
    [autosave, setDocTypeBoth],
  )

  // Keep the displayed title and type in sync with the server while not editing.
  useEffect(() => {
    if (!editing) setTitleBoth(document.title)
  }, [document.title, editing, setTitleBoth])

  useEffect(() => {
    if (!editing) {
      setDocTypeBoth(document.doc_type ?? null)
      savedDocTypeRef.current = document.doc_type ?? null
    }
  }, [document.doc_type, editing, setDocTypeBoth])

  // ---- view-mode polling: "new version available" ---------------------------
  const polled = useDocumentPolling(documentId, !editing)
  const newerVersion =
    !editing && polled.data && polled.data.version > loadedVersion
      ? polled.data
      : null
  const refreshToLatest = useCallback(() => {
    const fresh = polled.data
    if (!fresh) return
    htmlRef.current = fresh.content_html
    setTitleBoth(fresh.title)
    setDocTypeBoth(fresh.doc_type ?? null)
    editor?.commands.setContent(fresh.content_html, { emitUpdate: false })
    setLoadedVersion(fresh.version)
  }, [editor, polled.data, setTitleBoth, setDocTypeBoth])

  // ---- embeddings ------------------------------------------------------------
  const embedding = useEmbeddingStatus(documentId, document.namespace_id)
  const embeddingInfo = useMemo(
    () => ({
      state: embedding.data ? embedding.state : deriveFromDocument(document),
      progress: embedding.progress,
      chunkCount: embedding.data?.chunk_count ?? document.chunk_count,
      chunkingMethod:
        embedding.data?.chunking_method ?? document.chunking_method,
      updatedAt:
        embedding.data?.embedding_updated_at ?? document.embedding_updated_at,
      error: embedding.data?.embedding_error ?? document.embedding_error,
      attempts:
        embedding.data?.embedding_attempts ?? document.embedding_attempts,
      maxAttempts: embedding.currentJob?.max_attempts ?? 3,
    }),
    [embedding, document],
  )

  // ---- mode switching --------------------------------------------------------
  const enterEdit = useCallback(() => {
    if (!canEdit) return
    onChangeSearch({ mode: "edit" })
    requestAnimationFrame(() => editor?.commands.focus("end"))
  }, [canEdit, editor, onChangeSearch])

  const finishEditing = useCallback(async () => {
    setFinishing(true)
    try {
      const ok = await autosave.flush()
      if (ok || autosave.status === "clean" || autosave.status === "saved") {
        onChangeSearch({ mode: "view" })
      }
    } finally {
      setFinishing(false)
    }
  }, [autosave, onChangeSearch])

  // ---- panels ----------------------------------------------------------------
  const tocEntries = useToc(editor)
  const showToc =
    panel === "toc" || (panel === undefined && tocEntries.length >= 2)
  const aiOpen = panel === "ai"
  const toggleAi = useCallback(
    () => onChangeSearch({ panel: aiOpen ? undefined : "ai" }),
    [aiOpen, onChangeSearch],
  )
  // the imported-from file gets a rail card even with no panel open
  const hasRail = aiOpen || showToc || Boolean(document.source_attachment)

  // ---- keyboard shortcuts ----------------------------------------------------
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey) {
        return
      }
      if (e.altKey && e.key.toLowerCase() === "i") {
        e.preventDefault()
        toggleAi()
        return
      }
      if (e.altKey) return
      if (e.key === "e" && !editing && canEdit && !isTypingTarget(e.target)) {
        e.preventDefault()
        enterEdit()
      } else if (
        e.key === "Escape" &&
        editing &&
        (autosave.status === "saved" || autosave.status === "clean")
      ) {
        onChangeSearch({ mode: "view" })
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [editing, canEdit, enterEdit, autosave.status, onChangeSearch, toggleAi])

  // ---- leave guard: flush before navigating away ----------------------------
  const blocker = useBlocker({
    disabled: !editing,
    withResolver: true,
    shouldBlockFn: async () => {
      const current = autosaveRef.current
      if (!current) return false
      if (
        !current.isDirty &&
        current.status !== "saving" &&
        current.status !== "error"
      ) {
        return false
      }
      if (current.status === "conflict") return true
      const ok = await current.flush()
      return !ok
    },
  })

  // ---- breadcrumbs (space › folders › title) ---------------------------------
  const matches = useMatches()
  const setCrumbs = useCrumbsStore((s) => s.setCrumbs)
  useEffect(() => {
    const namespace = queryClient.getQueryData<NamespacePublic>(
      queryKeys.namespaces.bySlug(namespaceSlug),
    )
    const tree = queryClient.getQueryData<NamespaceTree>(
      queryKeys.namespaces.tree(document.namespace_id),
    )
    const parentCrumbs: Crumb[] = []
    for (const match of matches) {
      if (match.routeId.includes("/d/$documentId")) break
      const loaderCrumbs = (
        match.loaderData as { crumbs?: Crumb[] } | undefined
      )?.crumbs
      if (Array.isArray(loaderCrumbs)) parentCrumbs.push(...loaderCrumbs)
      else if (match.staticData?.crumb)
        parentCrumbs.push({ label: match.staticData.crumb, to: match.pathname })
    }
    const crumbs: Crumb[] =
      parentCrumbs.length > 0
        ? parentCrumbs
        : [
            {
              label: namespace?.name ?? namespaceSlug,
              to: `/s/${namespaceSlug}`,
            },
          ]
    if (tree) {
      for (const folder of folderPath(
        tree.folders,
        document.folder_id ?? null,
      )) {
        crumbs.push({
          label: folder.name,
          to: `/s/${namespaceSlug}/f/${folder.id}`,
        })
      }
    }
    crumbs.push({ label: title.trim() || "Untitled" })
    setCrumbs(crumbs)
    return () => setCrumbs(null)
  }, [
    matches,
    namespaceSlug,
    document.namespace_id,
    document.folder_id,
    title,
    queryClient,
    setCrumbs,
  ])

  // ---- render ----------------------------------------------------------------
  const sourceCard = document.source_attachment ? (
    <SourceFileCard attachment={document.source_attachment} />
  ) : null

  const railPanel = aiOpen ? (
    <Suspense fallback={<Skeleton className="h-64 w-full" />}>
      <AiIndexPanel
        documentId={documentId}
        namespaceId={document.namespace_id}
        namespaceSlug={namespaceSlug}
        canEdit={canEdit}
        onClose={() => onChangeSearch({ panel: undefined })}
      />
    </Suspense>
  ) : showToc ? (
    <TableOfContents editor={editor} />
  ) : null

  const rail =
    railPanel || sourceCard ? (
      <div className="flex flex-col gap-4">
        {sourceCard}
        {railPanel}
      </div>
    ) : null

  return (
    <div
      className="flex w-full justify-center gap-8 px-4 py-6 md:px-8 md:py-8"
      data-testid="document-page"
      data-mode={mode}
    >
      <article className="kb-editor-column flex min-w-0 w-full flex-col gap-6">
        <DocumentHeader
          document={document}
          namespaceSlug={namespaceSlug}
          title={title}
          onTitleChange={onTitleChange}
          onTitleSubmit={() => editor?.commands.focus("start")}
          mode={mode}
          docType={docType}
          onDocTypeChange={onDocTypeChange}
          canEdit={canEdit}
          onEdit={enterEdit}
          onDone={() => void finishEditing()}
          finishing={finishing}
          autosave={autosave}
          embedding={embeddingInfo}
          aiPanelOpen={aiOpen}
          onToggleAiPanel={toggleAi}
          extra={
            <>
              {document.source_attachment && (
                <SourceFileChip attachment={document.source_attachment} />
              )}
              {newerVersion && (
                <NewVersionChip
                  version={newerVersion.version}
                  onRefresh={refreshToLatest}
                />
              )}
              {!aiOpen && !showToc && tocEntries.length >= 2 && !isMobile && (
                <Button
                  variant="ghost"
                  size="xs"
                  className="text-muted-foreground"
                  onClick={() => onChangeSearch({ panel: "toc" })}
                >
                  <ListTree className="size-3.5" />
                  Contents
                </Button>
              )}
            </>
          }
        />

        {autosave.status === "conflict" && autosave.conflict && (
          <ConflictBanner
            conflict={autosave.conflict}
            onReload={() => void autosave.resolveConflict("reload")}
            onOverwrite={() => void autosave.resolveConflict("overwrite")}
          />
        )}

        {editing && editor && (
          <EditorToolbar
            editor={editor}
            uploadImage={canEdit ? uploadImage : null}
          />
        )}

        <div
          className={cn(
            "min-h-[50vh]",
            editing &&
              "rounded-lg border border-dashed border-transparent transition-colors focus-within:border-border",
          )}
        >
          <Editor editor={editor} withMenus={editing} />
          {editing && (
            // clicking the empty area below the content focuses the editor
            <button
              type="button"
              tabIndex={-1}
              aria-label="Continue writing"
              className="block h-24 w-full cursor-text"
              onClick={() => editor?.commands.focus("end")}
            />
          )}
        </div>
      </article>

      {hasRail && !isMobile && (
        <aside
          className="hidden w-[320px] shrink-0 lg:block"
          data-testid="document-rail"
          data-panel={aiOpen ? "ai" : "toc"}
        >
          <div className="sticky top-20 max-h-[calc(100vh-6rem)] overflow-y-auto pr-1">
            {rail}
          </div>
        </aside>
      )}

      {isMobile && (
        <Sheet
          open={Boolean(panel)}
          onOpenChange={(open) => !open && onChangeSearch({ panel: undefined })}
        >
          <SheetContent
            side="right"
            className="w-[92vw] overflow-y-auto sm:max-w-md"
          >
            <SheetHeader>
              <SheetTitle>{aiOpen ? "AI index" : "On this page"}</SheetTitle>
            </SheetHeader>
            <div className="px-4 pb-6">{rail}</div>
          </SheetContent>
        </Sheet>
      )}

      <AlertDialog open={blocker.status === "blocked"}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Unsaved changes</AlertDialogTitle>
            <AlertDialogDescription>
              {autosave.status === "conflict"
                ? "This page has a save conflict. Resolve it before leaving, or discard your changes."
                : "Your latest changes could not be saved. Leave anyway and lose them, or stay and retry."}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel
              onClick={() => blocker.status === "blocked" && blocker.reset()}
            >
              Stay
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={() => blocker.status === "blocked" && blocker.proceed()}
            >
              Leave anyway
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}

function deriveFromDocument(document: DocumentPublic) {
  // Lazy import avoided: inline the derivation used by the pill before the
  // embeddings query resolves.
  const status = document.embedding_status
  if (status === "ready")
    return document.is_stale ? ("stale" as const) : ("ready" as const)
  if (status === "failed") return "failed" as const
  return status
}

export default DocumentPage
