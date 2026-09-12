import { mergeAttributes, Node } from "@tiptap/core"

export const PANEL_TYPES = [
  "info",
  "note",
  "success",
  "warning",
  "error",
] as const
export type PanelType = (typeof PANEL_TYPES)[number]

export const PANEL_LABELS: Record<PanelType, string> = {
  info: "Info",
  note: "Note",
  success: "Success",
  warning: "Warning",
  error: "Error",
}

declare module "@tiptap/core" {
  interface Commands<ReturnType> {
    panel: {
      /** Wrap the selection in a panel of the given type. */
      setPanel: (type?: PanelType) => ReturnType
      /** Change the type of the panel around the selection. */
      updatePanelType: (type: PanelType) => ReturnType
      /** Lift the content out of the panel. */
      unsetPanel: () => ReturnType
      /** Toggle a panel around the selection. */
      togglePanel: (type?: PanelType) => ReturnType
    }
  }
}

/**
 * Confluence-style callout. Serialises to
 * `<div data-panel data-panel-type="warning" class="kb-panel kb-panel-warning">…</div>`.
 * Styling keys off `data-panel-type` so it survives even if `class` is stripped.
 */
export const Panel = Node.create({
  name: "panel",
  group: "block",
  content: "block+",
  defining: true,

  addAttributes() {
    return {
      type: {
        default: "info" as PanelType,
        parseHTML: (element) => {
          const value = element.getAttribute("data-panel-type")
          return PANEL_TYPES.includes(value as PanelType) ? value : "info"
        },
        renderHTML: (attributes) => ({
          "data-panel-type": attributes.type,
        }),
      },
    }
  },

  parseHTML() {
    return [{ tag: "div[data-panel]" }]
  },

  renderHTML({ HTMLAttributes }) {
    const type = HTMLAttributes["data-panel-type"] ?? "info"
    return [
      "div",
      mergeAttributes(HTMLAttributes, {
        "data-panel": "",
        class: `kb-panel kb-panel-${type}`,
      }),
      0,
    ]
  },

  addCommands() {
    return {
      setPanel:
        (type = "info") =>
        ({ commands }) =>
          commands.wrapIn(this.name, { type }),
      updatePanelType:
        (type) =>
        ({ commands }) =>
          commands.updateAttributes(this.name, { type }),
      unsetPanel:
        () =>
        ({ commands }) =>
          commands.lift(this.name),
      togglePanel:
        (type = "info") =>
        ({ commands, editor }) =>
          editor.isActive(this.name)
            ? commands.lift(this.name)
            : commands.wrapIn(this.name, { type }),
    }
  },

  addKeyboardShortcuts() {
    return {
      "Mod-Alt-p": () => this.editor.commands.togglePanel("info"),
    }
  },
})

export default Panel
