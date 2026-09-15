/**
 * Recovering from a deploy that happened while somebody was using the app.
 *
 * Routes are code-split, so opening one fetches a chunk whose filename carries
 * a content hash. A deploy replaces those files. A tab that was already open
 * still holds the old module graph, so the first navigation after a deploy asks
 * for a chunk that is no longer there and React shows "Failed to fetch
 * dynamically imported module" — which is true, unhelpful, and looks like the
 * application is broken when it has only moved.
 *
 * The fix is to reload: the new shell names the new chunks. What matters is
 * doing it **once**. A reload that fails the same way again would loop, and a
 * reload loop is worse than the error it replaces, so the attempt is recorded
 * in `sessionStorage` and a second failure is left to surface normally.
 *
 * Caching is the other half of this and is handled at the edge: the shell is
 * served `no-cache` on every route, so a reload genuinely fetches a new one.
 */

const ATTEMPTED = "stale-build-reload"

/**
 * How long one recovery attempt suppresses the next.
 *
 * Time rather than a flag cleared at start-up: clearing it on boot would let a
 * genuinely broken deploy - one whose chunks really are missing - reload,
 * clear, fail, reload, for ever. A window breaks that loop and still lets a
 * session recover from a *later* deploy an hour on.
 */
const COOLDOWN_MS = 60_000

/** Whether this error is a chunk that is no longer on the server. */
export function isStaleChunkError(error: unknown): boolean {
  const message =
    error instanceof Error
      ? error.message
      : typeof error === "string"
        ? error
        : ""
  return (
    /Failed to fetch dynamically imported module/i.test(message) ||
    /error loading dynamically imported module/i.test(message) ||
    /Importing a module script failed/i.test(message) ||
    // Safari's wording for the same thing.
    /Unable to preload CSS/i.test(message)
  )
}

/**
 * Reload once to pick up the current build.
 *
 * Returns whether a reload was started, so a caller can keep showing its error
 * when one was not — the page is about to go away if it was.
 */
export function reloadForNewBuild(): boolean {
  try {
    const last = Number(sessionStorage.getItem(ATTEMPTED) ?? 0)
    if (last && Date.now() - last < COOLDOWN_MS) return false
    sessionStorage.setItem(ATTEMPTED, String(Date.now()))
  } catch {
    // Private mode, or storage disabled. One reload is still better than a
    // dead page; without the guard it could loop, so do nothing instead.
    return false
  }
  window.location.reload()
  return true
}

/**
 * Catch the failures that never reach a React error boundary.
 *
 * Vite fires `vite:preloadError` when a dynamic import fails, and an unhandled
 * rejection covers the rest. Both happen outside the render tree, which is why
 * a route-level error component alone is not enough.
 */
export function watchForStaleBuild(): void {
  window.addEventListener("vite:preloadError", (event) => {
    event.preventDefault()
    reloadForNewBuild()
  })
  window.addEventListener("unhandledrejection", (event) => {
    if (isStaleChunkError(event.reason)) {
      event.preventDefault()
      reloadForNewBuild()
    }
  })
}
