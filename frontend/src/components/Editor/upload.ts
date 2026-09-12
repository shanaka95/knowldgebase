import type { Editor } from "@tiptap/core"
import { toast } from "sonner"
import { create } from "zustand"

export interface UploadedImage {
  id: string
  url: string
}

export type UploadImageFn = (file: File) => Promise<UploadedImage>

export const MAX_IMAGE_BYTES = 25 * 1024 * 1024
export const ACCEPTED_IMAGE_TYPES = [
  "image/png",
  "image/jpeg",
  "image/gif",
  "image/webp",
  "image/svg+xml",
]

/** Number of uploads in flight across all editors — autosave waits for 0. */
interface PendingUploadsState {
  count: number
  increment: () => void
  decrement: () => void
}

export const usePendingUploads = create<PendingUploadsState>((set) => ({
  count: 0,
  increment: () => set((s) => ({ count: s.count + 1 })),
  decrement: () => set((s) => ({ count: Math.max(0, s.count - 1) })),
}))

function validateImage(file: File): string | null {
  if (!ACCEPTED_IMAGE_TYPES.includes(file.type)) {
    return `Unsupported image type: ${file.type || "unknown"}`
  }
  if (file.size > MAX_IMAGE_BYTES) {
    return "Images must be smaller than 25 MB"
  }
  return null
}

/**
 * Insert an instant local preview of `file`, upload it, then swap the node's
 * attributes to the persistent attachment URL. On failure the node is removed.
 */
export async function insertImageFromFile(
  editor: Editor,
  file: File,
  upload: UploadImageFn | null | undefined,
  position?: number,
): Promise<void> {
  const problem = validateImage(file)
  if (problem) {
    toast.error("Couldn't add image", { description: problem })
    return
  }
  if (!upload) {
    toast.error("Image uploads are not available here")
    return
  }

  const previewUrl = URL.createObjectURL(file)
  const pos = position ?? editor.state.selection.to
  const { increment, decrement } = usePendingUploads.getState()

  editor
    .chain()
    .focus()
    .insertContentAt(pos, {
      type: "image",
      attrs: { src: previewUrl, alt: file.name, uploading: true },
    })
    .run()

  increment()
  try {
    const result = await upload(file)
    let replaced = false
    editor.state.doc.descendants((node, nodePos) => {
      if (replaced) return false
      if (node.type.name === "image" && node.attrs.src === previewUrl) {
        editor.view.dispatch(
          editor.state.tr.setNodeMarkup(nodePos, undefined, {
            ...node.attrs,
            src: result.url,
            "data-attachment-id": result.id,
            uploading: false,
          }),
        )
        replaced = true
        return false
      }
      return true
    })
  } catch (error) {
    editor.state.doc.descendants((node, nodePos) => {
      if (node.type.name === "image" && node.attrs.src === previewUrl) {
        editor.view.dispatch(
          editor.state.tr.delete(nodePos, nodePos + node.nodeSize),
        )
        return false
      }
      return true
    })
    const description =
      error instanceof Error
        ? error.message
        : "Upload failed. Please try again."
    toast.error("Image upload failed", { description })
  } finally {
    decrement()
    // give the swapped <img> a tick before revoking the preview
    setTimeout(() => URL.revokeObjectURL(previewUrl), 5_000)
  }
}

/** Open a file picker and insert the chosen image(s). */
export function pickAndInsertImage(
  editor: Editor,
  upload: UploadImageFn | null | undefined,
) {
  const input = document.createElement("input")
  input.type = "file"
  input.accept = ACCEPTED_IMAGE_TYPES.join(",")
  input.multiple = true
  input.onchange = () => {
    const files = Array.from(input.files ?? [])
    for (const file of files) {
      void insertImageFromFile(editor, file, upload)
    }
  }
  input.click()
}
