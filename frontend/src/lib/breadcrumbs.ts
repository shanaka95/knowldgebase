import { create } from "zustand"

/**
 * Breadcrumb convention
 * ---------------------
 * 1. Static pages declare `staticData: { crumb: "Settings" }` on their route.
 * 2. Dynamic pages return `crumbs: Crumb[]` from their `loader` (it is read from
 *    `match.loaderData.crumbs`).
 * 3. A page that needs live crumbs (e.g. a document title while typing) can call
 *    `useCrumbsStore.getState().setCrumbs([...])` and reset with `null` on unmount.
 */
export type Crumb = {
  label: string
  to?: string
  icon?: React.ReactNode
}

declare module "@tanstack/react-router" {
  interface StaticDataRouteOption {
    crumb?: string
  }
}

interface CrumbsState {
  override: Crumb[] | null
  setCrumbs: (crumbs: Crumb[] | null) => void
}

export const useCrumbsStore = create<CrumbsState>((set) => ({
  override: null,
  setCrumbs: (override) => set({ override }),
}))
