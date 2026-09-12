import { createFileRoute, notFound } from "@tanstack/react-router"
import { useCallback, useRef, useState } from "react"

import { SaveIndicator } from "@/components/Documents/SaveIndicator"
import { Editor } from "@/components/Editor/Editor"
import { EditorToolbar } from "@/components/Editor/EditorToolbar"
import { TableOfContents } from "@/components/Editor/TableOfContents"
import { usePendingUploads } from "@/components/Editor/upload"
import { useDocumentEditor } from "@/components/Editor/useDocumentEditor"
import { EmbeddingStatusIcon } from "@/components/Embeddings/EmbeddingStatusIcon"
import { EmbeddingStatusPill } from "@/components/Embeddings/EmbeddingStatusPill"
import { PageContainer } from "@/components/Layout/PageContainer"
import { Button } from "@/components/ui/button"
import { Switch } from "@/components/ui/switch"
import { type AutosaveStatus, useAutosave } from "@/hooks/useAutosave"
import type { EmbeddingState } from "@/lib/embeddingState"

/** Dev-only sandbox to eyeball the editor, save indicator and embedding pills. */
export const Route = createFileRoute("/_layout/playground")({
  component: Playground,
  staticData: { crumb: "Playground" },
  beforeLoad: () => {
    if (!import.meta.env.DEV) throw notFound()
  },
})

const SAMPLE = `
<h1>Onboarding guide</h1>
<p>Welcome to the <strong>PlusGPT</strong>. This page shows every block the editor supports. Type <code>/</code> anywhere to insert a block.</p>
<div data-panel data-panel-type="info"><p>Panels are great for tips, caveats and callouts. Select one to switch its type.</p></div>
<h2>Getting started</h2>
<ul>
  <li>Create a <em>space</em> for a team or a project</li>
  <li>Organise pages in nested folders</li>
  <li>Share a page or a whole space with colleagues</li>
</ul>
<h3>Checklist</h3>
<ul data-type="taskList">
  <li data-type="taskItem" data-checked="true"><label><input type="checkbox" checked></label><div><p>Install Docker</p></div></li>
  <li data-type="taskItem" data-checked="false"><label><input type="checkbox"></label><div><p>Run <code>docker compose up</code></p></div></li>
</ul>
<h2>Architecture</h2>
<table>
  <tr><th>Service</th><th>Port</th><th>Purpose</th></tr>
  <tr><td>Backend</td><td>8800</td><td>FastAPI + worker</td></tr>
  <tr><td>Qdrant</td><td>6333</td><td>Vectors</td></tr>
  <tr><td>MinIO</td><td>9000</td><td>Attachments</td></tr>
</table>
<h3>Example</h3>
<pre><code class="language-python">def greet(name: str) -> str:
    return f"Hello, {name}!"</code></pre>
<div data-panel data-panel-type="warning"><p>Never commit <code>.env</code> files with real secrets.</p></div>
<blockquote><p>Documentation is a love letter that you write to your future self.</p></blockquote>
<p style="text-align: center">— centred text —</p>
`

const STATUSES: AutosaveStatus[] = [
  "clean",
  "dirty",
  "saving",
  "blocked",
  "saved",
  "error",
  "conflict",
]

const EMBEDDING_STATES: EmbeddingState[] = [
  "none",
  "pending",
  "chunking",
  "summarizing",
  "embedding",
  "ready",
  "stale",
  "failed",
]

function Playground() {
  const [editable, setEditable] = useState(true)
  const [version, setVersion] = useState(1)
  const htmlRef = useRef(SAMPLE)
  const pendingUploads = usePendingUploads((s) => s.count)

  const fakeUpload = useCallback(async (file: File) => {
    await new Promise((r) => setTimeout(r, 1200))
    return { id: crypto.randomUUID(), url: URL.createObjectURL(file) }
  }, [])

  const autosave = useAutosave<{ html: string }>({
    save: async () => {
      await new Promise((r) => setTimeout(r, 600))
      const next = version + 1
      setVersion(next)
      return { version: next }
    },
    getPayload: () => ({ html: htmlRef.current }),
    baseVersion: version,
    enabled: editable,
    isBlocked: () => usePendingUploads.getState().count > 0,
  })

  const editor = useDocumentEditor({
    content: SAMPLE,
    editable,
    uploadImage: fakeUpload,
    fetchAttachmentBlob: async () => new Blob(),
    onUpdate: (html) => {
      htmlRef.current = html
      autosave.markDirty()
    },
  })

  return (
    <PageContainer size="wide" className="flex flex-col gap-8">
      <section className="flex flex-col gap-3">
        <h2 className="text-sm font-medium text-muted-foreground">
          Save indicator states
        </h2>
        <div className="flex flex-wrap gap-6 rounded-lg border p-4">
          {STATUSES.map((s) => (
            <div key={s} className="flex flex-col gap-1">
              <span className="text-[10px] uppercase text-muted-foreground">
                {s}
              </span>
              <SaveIndicator
                status={s}
                lastSavedAt={new Date(Date.now() - 3 * 60_000)}
                error="Network error"
                onRetry={() => {}}
              />
            </div>
          ))}
        </div>
      </section>

      <section className="flex flex-col gap-3">
        <h2 className="text-sm font-medium text-muted-foreground">
          Embedding status
        </h2>
        <div className="flex flex-wrap items-center gap-3 rounded-lg border p-4">
          {EMBEDDING_STATES.map((s) => (
            <EmbeddingStatusPill
              key={s}
              state={s}
              progress={s === "embedding" ? 45 : null}
              attempts={s === "pending" ? 2 : null}
              maxAttempts={3}
              chunkCount={s === "ready" ? 7 : null}
              chunkingMethod={s === "ready" ? "llm" : null}
              onClick={() => {}}
            />
          ))}
          <span className="mx-2 h-5 w-px bg-border" />
          {EMBEDDING_STATES.map((s) => (
            <EmbeddingStatusIcon key={s} state={s} hideWhenReady={false} />
          ))}
        </div>
      </section>

      <section className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-sm font-medium text-muted-foreground">Editor</h2>
          <div className="flex items-center gap-4 text-sm">
            <label htmlFor="pg-editable" className="flex items-center gap-2">
              <Switch
                id="pg-editable"
                checked={editable}
                onCheckedChange={setEditable}
              />
              Editable
            </label>
            <SaveIndicator
              status={autosave.status}
              lastSavedAt={autosave.lastSavedAt}
              error={autosave.error}
              onRetry={() => void autosave.retry()}
            />
            <span className="text-xs text-muted-foreground">
              v{autosave.version} · uploads {pendingUploads}
            </span>
            <Button
              size="sm"
              variant="outline"
              onClick={() => void autosave.flush()}
            >
              Save now
            </Button>
          </div>
        </div>
        {autosave.status === "conflict" && (
          <div className="flex items-center justify-between rounded-md border border-warning/40 bg-warning/10 p-3 text-sm">
            <span>{autosave.conflict?.message}</span>
            <div className="flex gap-2">
              <Button
                size="sm"
                variant="outline"
                onClick={() => void autosave.resolveConflict("reload")}
              >
                Reload latest
              </Button>
              <Button
                size="sm"
                onClick={() => void autosave.resolveConflict("overwrite")}
              >
                Overwrite
              </Button>
            </div>
          </div>
        )}
        <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_240px]">
          <div className="kb-editor-column flex flex-col gap-4">
            {editor && editable && (
              <EditorToolbar editor={editor} uploadImage={fakeUpload} />
            )}
            <div className="rounded-lg border p-6 md:p-10">
              <Editor editor={editor} />
            </div>
          </div>
          <aside className="hidden lg:block">
            <div className="sticky top-20">
              <TableOfContents editor={editor} />
            </div>
          </aside>
        </div>
      </section>
    </PageContainer>
  )
}
