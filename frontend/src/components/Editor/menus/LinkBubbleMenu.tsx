import type { Editor } from "@tiptap/core"
import { useEditorState } from "@tiptap/react"
import { BubbleMenu } from "@tiptap/react/menus"
import { Check, ExternalLink, Pencil, Unlink, X } from "lucide-react"
import { useEffect, useState } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { MenuButton, MenuDivider, menuSurface } from "./MenuButton"

function normaliseUrl(value: string): string | null {
  const trimmed = value.trim()
  if (!trimmed) return null
  if (/^(https?:\/\/|mailto:|\/)/i.test(trimmed)) return trimmed
  if (/^[\w.-]+\.[a-z]{2,}(\/.*)?$/i.test(trimmed)) return `https://${trimmed}`
  return null
}

export function LinkBubbleMenu({ editor }: { editor: Editor }) {
  const { href, editable } = useEditorState({
    editor,
    selector: ({ editor }) => ({
      href: (editor.getAttributes("link").href as string | undefined) ?? "",
      editable: editor.isEditable,
    }),
  })
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState(href)
  const [invalid, setInvalid] = useState(false)

  useEffect(() => {
    setValue(href)
    setEditing(false)
    setInvalid(false)
  }, [href])

  const commit = () => {
    const url = normaliseUrl(value)
    if (!url) {
      setInvalid(true)
      return
    }
    editor.chain().focus().extendMarkRange("link").setLink({ href: url }).run()
    setEditing(false)
  }

  return (
    <BubbleMenu
      editor={editor}
      pluginKey="linkBubbleMenu"
      updateDelay={0}
      options={{ placement: "bottom", offset: 6 }}
      shouldShow={({ editor, from, to }) =>
        editor.isEditable && from === to && editor.isActive("link")
      }
      className={menuSurface}
    >
      {editing ? (
        <form
          className="flex items-center gap-1"
          onSubmit={(e) => {
            e.preventDefault()
            commit()
          }}
        >
          <Input
            autoFocus
            value={value}
            aria-invalid={invalid}
            onChange={(e) => {
              setValue(e.target.value)
              setInvalid(false)
            }}
            onKeyDown={(e) => {
              if (e.key === "Escape") setEditing(false)
            }}
            placeholder="https://example.com"
            className="h-8 w-64 text-xs"
          />
          <Button
            type="submit"
            size="icon-sm"
            variant="ghost"
            aria-label="Save link"
          >
            <Check />
          </Button>
          <Button
            type="button"
            size="icon-sm"
            variant="ghost"
            aria-label="Cancel"
            onClick={() => setEditing(false)}
          >
            <X />
          </Button>
        </form>
      ) : (
        <>
          <a
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            className="max-w-64 truncate px-2 text-xs text-primary underline-offset-2 hover:underline"
          >
            {href}
          </a>
          <MenuDivider />
          <MenuButton
            icon={ExternalLink}
            label="Open link"
            onClick={() => window.open(href, "_blank", "noopener,noreferrer")}
          />
          <MenuButton
            icon={Pencil}
            label="Edit link"
            disabled={!editable}
            onClick={() => setEditing(true)}
          />
          <MenuButton
            icon={Unlink}
            label="Remove link"
            destructive
            disabled={!editable}
            onClick={() =>
              editor.chain().focus().extendMarkRange("link").unsetLink().run()
            }
          />
        </>
      )}
    </BubbleMenu>
  )
}
