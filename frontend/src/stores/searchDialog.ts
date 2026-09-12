import { create } from "zustand"

/** Shared open/close state for the ⌘K command palette (mounted by the search feature). */
interface SearchDialogState {
  isOpen: boolean
  open: () => void
  close: () => void
  toggle: () => void
  setOpen: (open: boolean) => void
}

export const useSearchDialogStore = create<SearchDialogState>((set) => ({
  isOpen: false,
  open: () => set({ isOpen: true }),
  close: () => set({ isOpen: false }),
  toggle: () => set((s) => ({ isOpen: !s.isOpen })),
  setOpen: (isOpen) => set({ isOpen }),
}))
