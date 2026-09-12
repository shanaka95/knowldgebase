import { type Editor, Extension, type Range } from "@tiptap/core"
import { ReactRenderer } from "@tiptap/react"
import Suggestion, {
  type SuggestionKeyDownProps,
  type SuggestionProps,
} from "@tiptap/suggestion"

import type { UploadImageFn } from "../upload"
import { buildSlashItems, filterSlashItems, type SlashItem } from "./items"
import { SlashMenu, type SlashMenuHandle } from "./SlashMenu"

export interface SlashCommandOptions {
  uploadImage: UploadImageFn | null
}

/**
 * "/" command menu built on @tiptap/suggestion. Positioning uses the
 * suggestion plugin's built-in Floating UI mount (v3.31+).
 */
export const SlashCommand = Extension.create<SlashCommandOptions>({
  name: "slashCommand",

  addOptions() {
    return { uploadImage: null }
  },

  addProseMirrorPlugins() {
    const items = buildSlashItems({ uploadImage: this.options.uploadImage })

    return [
      Suggestion<SlashItem, SlashItem>({
        editor: this.editor,
        char: "/",
        allowSpaces: false,
        startOfLine: false,
        pluginKey: undefined,
        placement: "bottom-start",
        offset: { mainAxis: 6, crossAxis: 0 },
        flip: true,
        dismissOnOutsideClick: true,
        allow: ({ state, range }) => {
          const $from = state.doc.resolve(range.from)
          // don't offer block commands inside code blocks
          return $from.parent.type.name !== "codeBlock"
        },
        items: ({ query }) => filterSlashItems(items, query),
        command: ({
          editor,
          range,
          props,
        }: {
          editor: Editor
          range: Range
          props: SlashItem
        }) => {
          props.run(editor, range)
        },
        render: () => {
          let component: ReactRenderer<
            SlashMenuHandle,
            { items: SlashItem[]; command: (item: SlashItem) => void }
          > | null = null
          let unmount: (() => void) | null = null

          return {
            onStart: (props: SuggestionProps<SlashItem, SlashItem>) => {
              component = new ReactRenderer(SlashMenu, {
                props: { items: props.items, command: props.command },
                editor: props.editor,
              })
              component.element.style.position = "absolute"
              component.element.style.zIndex = "50"
              unmount = props.mount(component.element)
            },
            onUpdate: (props: SuggestionProps<SlashItem, SlashItem>) => {
              component?.updateProps({
                items: props.items,
                command: props.command,
              })
            },
            onKeyDown: (props: SuggestionKeyDownProps) => {
              if (props.event.key === "Escape") {
                unmount?.()
                unmount = null
                component?.destroy()
                component = null
                return true
              }
              return component?.ref?.onKeyDown(props.event) ?? false
            },
            onExit: () => {
              unmount?.()
              unmount = null
              component?.destroy()
              component = null
            },
          }
        },
      }),
    ]
  },
})

export default SlashCommand
