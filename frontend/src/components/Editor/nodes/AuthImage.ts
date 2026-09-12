import Image, { type ImageOptions } from "@tiptap/extension-image"
import { ReactNodeViewRenderer } from "@tiptap/react"

import { AuthImageView } from "./AuthImageView"

export interface AuthImageOptions extends ImageOptions {
  /**
   * Fetch the bytes of an attachment with the caller's credentials. The
   * returned Blob is turned into an object URL by the node view.
   */
  fetchAttachmentBlob: ((attachmentId: string) => Promise<Blob>) | null
}

/**
 * Image node whose `src` points to an authenticated attachment endpoint.
 * Stored HTML: `<img src="/api/v1/attachments/{id}/download" alt="" data-attachment-id="{id}">`.
 * The React node view fetches the blob with the Authorization header because a
 * plain <img> cannot send one.
 */
export const AuthImage = Image.extend<AuthImageOptions>({
  name: "image",

  addOptions() {
    const parent = this.parent?.() ?? ({} as ImageOptions)
    return {
      ...parent,
      inline: false,
      allowBase64: false,
      fetchAttachmentBlob: null,
      HTMLAttributes: {},
    }
  },

  addAttributes() {
    return {
      ...this.parent?.(),
      "data-attachment-id": {
        default: null,
        parseHTML: (element) => element.getAttribute("data-attachment-id"),
        renderHTML: (attributes) =>
          attributes["data-attachment-id"]
            ? { "data-attachment-id": attributes["data-attachment-id"] }
            : {},
      },
      width: {
        default: null,
        parseHTML: (element) => element.getAttribute("width"),
        renderHTML: (attributes) =>
          attributes.width ? { width: attributes.width } : {},
      },
      /** Local-only flag while the upload is in flight (never serialised). */
      uploading: {
        default: false,
        rendered: false,
        parseHTML: () => false,
      },
    }
  },

  addNodeView() {
    return ReactNodeViewRenderer(AuthImageView)
  },
})

export default AuthImage
