import CodeBlockLowlight from "@tiptap/extension-code-block-lowlight"
import FileHandler from "@tiptap/extension-file-handler"
import Highlight from "@tiptap/extension-highlight"
import { TaskItem, TaskList } from "@tiptap/extension-list"
import Subscript from "@tiptap/extension-subscript"
import Superscript from "@tiptap/extension-superscript"
import { TableKit } from "@tiptap/extension-table"
import TextAlign from "@tiptap/extension-text-align"
import Typography from "@tiptap/extension-typography"
import { CharacterCount, Placeholder } from "@tiptap/extensions"
import StarterKit from "@tiptap/starter-kit"

import { lowlight } from "./lowlight"
import { AuthImage } from "./nodes/AuthImage"
import { Panel } from "./nodes/Panel"
import { SlashCommand } from "./slash/SlashCommand"
import { insertImageFromFile, type UploadImageFn } from "./upload"

export interface CreateExtensionsOptions {
  placeholder?: string
  /** Upload a dropped/pasted/picked image; null disables image insertion. */
  uploadImage?: UploadImageFn | null
  /** Fetch an attachment's bytes with credentials (for rendering stored images). */
  fetchAttachmentBlob?: ((attachmentId: string) => Promise<Blob>) | null
}

export function createExtensions({
  placeholder = "Type '/' for commands…",
  uploadImage = null,
  fetchAttachmentBlob = null,
}: CreateExtensionsOptions = {}) {
  return [
    StarterKit.configure({
      heading: { levels: [1, 2, 3, 4] },
      codeBlock: false,
      link: {
        openOnClick: false,
        autolink: true,
        defaultProtocol: "https",
        HTMLAttributes: { rel: "noopener noreferrer", target: "_blank" },
      },
      dropcursor: { width: 2, class: "kb-dropcursor" },
    }),
    CodeBlockLowlight.configure({
      lowlight,
      defaultLanguage: "plaintext",
    }),
    TableKit.configure({
      table: { resizable: false, HTMLAttributes: { class: "kb-table" } },
    }),
    TaskList,
    TaskItem.configure({ nested: true }),
    TextAlign.configure({ types: ["heading", "paragraph"] }),
    Highlight,
    Typography,
    Subscript,
    Superscript,
    Placeholder.configure({
      placeholder: ({ node }) =>
        node.type.name === "heading" ? "Heading" : placeholder,
      includeChildren: false,
    }),
    CharacterCount,
    Panel,
    AuthImage.configure({ fetchAttachmentBlob }),
    SlashCommand.configure({ uploadImage }),
    FileHandler.configure({
      allowedMimeTypes: [
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/webp",
        "image/svg+xml",
      ],
      onDrop: (editor, files, pos) => {
        for (const file of files) {
          void insertImageFromFile(editor, file, uploadImage, pos)
        }
      },
      consumePasteEvent: true,
      onPaste: (editor, files, htmlContent) => {
        // let Tiptap handle rich HTML pastes that already contain <img>
        if (htmlContent && /<img/i.test(htmlContent)) return
        for (const file of files) {
          void insertImageFromFile(editor, file, uploadImage)
        }
      },
    }),
  ]
}
