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
 * Whether this tab has already tried the expensive recovery.
 *
 * Separate from `ATTEMPTED`, because the two steps answer different questions
 * and the cheap one must not use up the thorough one.
 */
const REPAIRED = "stale-build-repaired"

/**
 * How long one recovery attempt suppresses the next.
 *
 * Time rather than a flag cleared at start-up: clearing it on boot would let a
 * genuinely broken deploy - one whose chunks really are missing - reload,
 * clear, fail, reload, for ever. A window breaks that loop and still lets a
 * session recover from a *later* deploy an hour on.
 */
const COOLDOWN_MS = 60_000

/**
 * Which build this tab is running, taken from the entry chunk's own URL.
 *
 * Set once at start-up by `watchForStaleBuild`. In development there are no
 * hashed chunks and this stays null, which turns the freshness check into a
 * no-op rather than something that guesses.
 */
let runningBuild: string | null = null

const ENTRY = /assets\/index-[A-Za-z0-9_-]+\.js/

/**
 * Whether the server is now serving a different build than this tab loaded.
 *
 * Asked rather than inferred. A replaced chunk does not always surface as a
 * failed import: a route can load enough to leave the router holding a match
 * whose route is undefined, and "Cannot read properties of undefined (reading
 * 'component')" is what that looks like from the outside. Matching on error
 * text would mean guessing at every future phrasing of the same thing, so the
 * question asked here is the one that actually decides it - is this tab out of
 * date? - and the answer comes from the shell.
 */
export async function isStaleBuild(): Promise<boolean> {
  if (!runningBuild) return false
  try {
    const response = await fetch("/", {
      cache: "no-store",
      headers: { Accept: "text/html" },
    })
    if (!response.ok) return false
    const current = ENTRY.exec(await response.text())?.[0]
    return Boolean(current) && current !== runningBuild
  } catch {
    // Offline, or the server is down. Neither is a stale build, and reloading
    // into a network failure helps nobody.
    return false
  }
}

/** Every built asset a page - or an error message - names. */
const ASSET_URL = /\/assets\/[A-Za-z0-9._-]+\.(?:js|css)/g

/**
 * Fetch the app's assets again, past the browser's cache.
 *
 * Assets are served `immutable`, which asks the browser never to revalidate
 * them - so if a request for one ever answered 404, that failure is held under
 * the same terms and an ordinary reload will not go back to the server to find
 * out otherwise. The origin used to send `immutable` on its 404s and 502s, and
 * a deploy has a few seconds with no upstream, which is all it takes. Chunk
 * filenames are content hashes and mostly survive a rebuild, so one poisoned
 * entry goes on breaking builds that had not been made yet.
 *
 * `cache: "reload"` is the one request that ignores the cache on the way out
 * and *overwrites* it on the way back, which is what makes this a repair rather
 * than another attempt. Everything the shell names is refreshed, not just what
 * failed: the failure is reported one chunk at a time and a deploy window does
 * not poison them one at a time.
 */
async function repairAssetCache(failed: readonly string[]): Promise<void> {
  const urls = new Set(failed)
  try {
    const shell = await fetch("/", {
      cache: "no-store",
      headers: { Accept: "text/html" },
    }).then((response) => (response.ok ? response.text() : ""))
    for (const match of shell.matchAll(ASSET_URL)) urls.add(match[0])
  } catch {
    // Offline. The repair below is still worth trying for what did fail.
  }
  // Settled, not all: one asset that is genuinely gone must not stop the rest
  // being repaired, and nothing here is worth failing over.
  await Promise.allSettled(
    [...urls].map((url) => fetch(url, { cache: "reload" })),
  )
}

/** The asset URLs an error message names, if it names any. */
export function assetsNamedIn(error: unknown): string[] {
  const message = error instanceof Error ? error.message : String(error ?? "")
  return [...message.matchAll(ASSET_URL)].map((match) => match[0])
}

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
 * Recover from a chunk that would not load, escalating rather than repeating.
 *
 * Three steps, each tried at most once per tab:
 *
 * 1. **Reload.** Cheap, and it is the whole answer when the tab was simply
 *    running a build the server has replaced.
 * 2. **Repair, then reload.** If a reload did not help, the browser is holding
 *    a cached failure that a reload cannot dislodge — see `repairAssetCache`.
 * 3. **Stop.** Two attempts have failed; a third would be a loop. The error
 *    surfaces with its own message, which names the asset.
 *
 * Returns whether recovery is under way, so a caller knows whether the page is
 * about to be replaced or whether it is the one that has to say what happened.
 * Never rejects: a recovery that throws is a page that shows nothing at all.
 */
export async function recoverFromStaleBuild(error: unknown): Promise<boolean> {
  if (reloadForNewBuild()) return true
  if (!once(REPAIRED)) return false
  try {
    await repairAssetCache(assetsNamedIn(error))
  } catch {
    // Reload anyway. A repair that failed halfway is still worth reloading
    // into, and there is nothing better left to try.
  }
  window.location.reload()
  return true
}

/**
 * Claim a one-time action for this tab, returning whether it was still unclaimed.
 *
 * `false` when storage is unavailable, not `true`: without somewhere to record
 * the attempt there is nothing to stop it repeating, and a reload loop is worse
 * than the error it replaces.
 */
function once(key: string): boolean {
  try {
    if (sessionStorage.getItem(key)) return false
    sessionStorage.setItem(key, String(Date.now()))
    return true
  } catch {
    return false
  }
}

/**
 * A stylesheet that failed to preload, which is survivable.
 *
 * Vite's preload helper reports two quite different things through one event.
 * It walks the route's dependencies first, and the only one that can reject is
 * a `<link rel=stylesheet>` - everything else is `modulepreload`, which it does
 * not wait on. That rejection is worth swallowing: the module import itself
 * still runs, the link is in the document either way, and a flaky stylesheet
 * fetch should not cost somebody the page.
 *
 * The other thing it reports is the module import failing, and that one is
 * fatal - see below.
 */
const CSS_PRELOAD = /Unable to preload CSS/i

/**
 * Catch the failures that never reach a React error boundary.
 *
 * Vite fires `vite:preloadError` when a dynamic import fails, and an unhandled
 * rejection covers the rest. Both happen outside the render tree, which is why
 * a route-level error component alone is not enough.
 *
 * **`preventDefault` here is not free.** Vite's helper is, in full:
 *
 * ```js
 * const onError = (err) => {
 *   const e = new Event("vite:preloadError", { cancelable: true })
 *   e.payload = err
 *   window.dispatchEvent(e)
 *   if (!e.defaultPrevented) throw err
 * }
 * return deps.then(() => importer().catch(onError))
 * ```
 *
 * Cancel the event and `onError` returns instead of throwing - so
 * `importer().catch(onError)` *resolves*, with `undefined`. The router then
 * reads `component` off that, and a momentary network failure surfaces for ever
 * after as `Cannot read properties of undefined (reading 'component')`, on a
 * page whose chunks are all present and correct. That cost three wrong
 * diagnoses before the minified helper was read.
 *
 * So the event is only cancelled when a reload is genuinely under way and the
 * page is about to be replaced. Otherwise it is left to throw, the import
 * rejects, and the failure arrives at the error boundary as what it actually
 * is - a chunk that would not load, which that boundary already knows how to
 * offer a reload for.
 */
export function watchForStaleBuild(entryUrl?: string): void {
  runningBuild = entryUrl ? (ENTRY.exec(entryUrl)?.[0] ?? null) : null

  window.addEventListener("vite:preloadError", (event) => {
    const reason = (event as Event & { payload?: unknown }).payload
    const message = reason instanceof Error ? reason.message : String(reason)
    if (CSS_PRELOAD.test(message)) {
      event.preventDefault()
      return
    }
    // Cancelled only if a reload is already under way. `recoverFromStaleBuild`
    // may yet repair and reload, but not before this handler has to return, and
    // cancelling on the strength of something that has not happened is what
    // turned a failed import into `undefined` in the first place.
    if (reloadForNewBuild()) {
      event.preventDefault()
      return
    }
    void recoverFromStaleBuild(reason)
  })
  window.addEventListener("unhandledrejection", (event) => {
    if (!isStaleChunkError(event.reason)) return
    // Cancelled only when reloading, for the same reason: otherwise this is the
    // last place the failure could have been printed.
    if (reloadForNewBuild()) {
      event.preventDefault()
      return
    }
    void recoverFromStaleBuild(event.reason)
  })
}

/**
 * Reload if - and only if - this tab is running a build the server has replaced.
 *
 * The caller keeps showing its error until this resolves, because most errors
 * are not this and a page that reloads itself on every failure hides real ones.
 */
export async function reloadIfStale(): Promise<boolean> {
  if (!(await isStaleBuild())) return false
  return recoverFromStaleBuild(null)
}
