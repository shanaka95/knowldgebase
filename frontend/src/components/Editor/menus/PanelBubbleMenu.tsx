import type { Editor } from "@tiptap/core"
import { useEditorState } from "@tiptap/react"
import { BubbleMenu } from "@tiptap/react/menus"
import {
  AlertOctagon,
  AlertTriangle,
  CheckCircle2,
  Info,
  type LucideIcon,
  Pencil,
  X,
} from "lucide-react"

import { PANEL_LABELS, PANEL_TYPES, type PanelType } from "../nodes/Panel"
import { MenuButton, MenuDivider, menuSurface } from "./MenuButton"

const ICONS: Record<PanelType, LucideIcon> = {
  info: Info,
  note: Pencil,
  success: CheckCircle2,
  warning: AlertTriangle,
  error: AlertOctagon,
}

export function PanelBubbleMenu({ editor }: { editor: Editor }) {
  const current = useEditorState({
    editor,
    selector: ({ editor }) =>
      (editor.getAttributes("panel").type as PanelType | undefined) ?? "info",
  })

  return (
    <BubbleMenu
      editor={editor}
      pluginKey="panelBubbleMenu"
      updateDelay={100}
      options={{ placement: "top-start", offset: 8 }}
      shouldShow={({ editor, state, from, to }) =>
        editor.isEditable &&
        editor.isActive("panel") &&
        from === to &&
        // keep the inline menu for text selections inside the panel
        state.doc.textBetween(from, to).length === 0
      }
      className={menuSurface}
    >
      {PANEL_TYPES.map((type) => (
        <MenuButton
          key={type}
          icon={ICONS[type]}
          label={`${PANEL_LABELS[type]} panel`}
          active={current === type}
          onClick={() => editor.chain().focus().updatePanelType(type).run()}
        />
      ))}
      <MenuDivider />
      <MenuButton
        icon={X}
        label="Remove panel"
        destructive
        onClick={() => editor.chain().focus().unsetPanel().run()}
      />
    </BubbleMenu>
  )
}
