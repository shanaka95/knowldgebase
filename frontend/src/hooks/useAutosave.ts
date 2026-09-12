import { AxiosError } from "axios"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"

export type AutosaveStatus =
  | "clean"
  | "dirty"
  | "saving"
  | "saved"
  | "error"
  | "conflict"
  | "blocked"

export interface AutosaveConflict {
  /** Version the server currently has, if it told us. */
  serverVersion: number | null
  message: string
}

export interface UseAutosaveOptions<P> {
  /** Persist the payload. Must reject with a 409 AxiosError on version conflict. */
  save: (payload: P, baseVersion: number) => Promise<{ version: number }>
  /** Build the payload from current editor state (called at flush time). */
  getPayload: () => P
  /** Version the local content is based on. */
  baseVersion: number
  /** Disable autosave (e.g. in view mode). Pending timers are cleared. */
  enabled?: boolean
  debounceMs?: number
  maxWaitMs?: number
  /** Return true to postpone flushing (e.g. uploads in flight). */
  isBlocked?: () => boolean
  /** Called after a successful save with the new version. */
  onSaved?: (version: number) => void
  /** Called for "reload latest" conflict resolution. */
  onReload?: () => Promise<void> | void
  /** Bind ⌘S, blur/visibility and beforeunload handlers. */
  bindWindowEvents?: boolean
}

export interface UseAutosaveResult {
  status: AutosaveStatus
  lastSavedAt: Date | null
  version: number
  error: string | null
  conflict: AutosaveConflict | null
  isDirty: boolean
  markDirty: () => void
  flush: () => Promise<boolean>
  retry: () => Promise<boolean>
  resolveConflict: (mode: "reload" | "overwrite") => Promise<void>
}

const RETRY_DELAYS = [2_000, 4_000, 8_000]

/**
 * Debounced autosave state machine:
 *   clean → dirty → saving → saved | error | conflict   (+ blocked while uploads pending)
 * Flushes on debounce, maxWait, ⌘S, window blur, tab hidden, and warns on unload.
 */
export function useAutosave<P>(
  options: UseAutosaveOptions<P>,
): UseAutosaveResult {
  const {
    enabled = true,
    debounceMs = 1_500,
    maxWaitMs = 10_000,
    bindWindowEvents = true,
  } = options

  const optionsRef = useRef(options)
  optionsRef.current = options

  const [status, setStatus] = useState<AutosaveStatus>("clean")
  const [lastSavedAt, setLastSavedAt] = useState<Date | null>(null)
  const [version, setVersion] = useState(options.baseVersion)
  const [error, setError] = useState<string | null>(null)
  const [conflict, setConflict] = useState<AutosaveConflict | null>(null)

  const versionRef = useRef(options.baseVersion)
  const dirtyRef = useRef(false)
  const dirtySinceSaveRef = useRef(false)
  const savingRef = useRef(false)
  const debounceTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const maxWaitTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const retryTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const retryCount = useRef(0)
  const blockedPoll = useRef<ReturnType<typeof setInterval> | null>(null)

  // keep version in sync when the parent supplies a fresh base (e.g. after reload)
  useEffect(() => {
    versionRef.current = options.baseVersion
    setVersion(options.baseVersion)
  }, [options.baseVersion])

  const clearTimers = useCallback(() => {
    if (debounceTimer.current) clearTimeout(debounceTimer.current)
    if (maxWaitTimer.current) clearTimeout(maxWaitTimer.current)
    if (retryTimer.current) clearTimeout(retryTimer.current)
    if (blockedPoll.current) clearInterval(blockedPoll.current)
    debounceTimer.current = null
    maxWaitTimer.current = null
    retryTimer.current = null
    blockedPoll.current = null
  }, [])

  const scheduleRef = useRef<() => void>(() => {})
  const schedule = useCallback(() => scheduleRef.current(), [])

  const performSave = useCallback(
    async (overrideVersion?: number): Promise<boolean> => {
      const opts = optionsRef.current
      if (savingRef.current) {
        dirtySinceSaveRef.current = true
        return false
      }
      if (opts.isBlocked?.()) {
        setStatus("blocked")
        if (!blockedPoll.current) {
          blockedPoll.current = setInterval(() => {
            if (!optionsRef.current.isBlocked?.()) {
              if (blockedPoll.current) clearInterval(blockedPoll.current)
              blockedPoll.current = null
              void performSave()
            }
          }, 500)
        }
        return false
      }
      if (debounceTimer.current) clearTimeout(debounceTimer.current)
      if (maxWaitTimer.current) clearTimeout(maxWaitTimer.current)
      debounceTimer.current = null
      maxWaitTimer.current = null

      savingRef.current = true
      dirtySinceSaveRef.current = false
      setStatus("saving")
      setError(null)
      const base = overrideVersion ?? versionRef.current
      try {
        const payload = opts.getPayload()
        const result = await opts.save(payload, base)
        versionRef.current = result.version
        setVersion(result.version)
        setLastSavedAt(new Date())
        retryCount.current = 0
        setConflict(null)
        opts.onSaved?.(result.version)
        savingRef.current = false
        if (dirtySinceSaveRef.current) {
          dirtyRef.current = true
          setStatus("dirty")
          schedule()
        } else {
          dirtyRef.current = false
          setStatus("saved")
        }
        return true
      } catch (err) {
        savingRef.current = false
        dirtyRef.current = true
        if (err instanceof AxiosError && err.response?.status === 409) {
          const data = err.response.data as
            | {
                detail?: string | { message?: string; current_version?: number }
              }
            | undefined
          const detail = data?.detail
          const serverVersion =
            typeof detail === "object" && detail?.current_version != null
              ? Number(detail.current_version)
              : null
          const message =
            typeof detail === "string"
              ? detail
              : (detail?.message ?? "Someone else updated this page.")
          setConflict({ serverVersion, message })
          setStatus("conflict")
          return false
        }
        const message =
          err instanceof AxiosError
            ? ((err.response?.data as { detail?: string } | undefined)
                ?.detail ?? err.message)
            : err instanceof Error
              ? err.message
              : "Couldn't save"
        setError(message)
        setStatus("error")
        const delay = RETRY_DELAYS[retryCount.current]
        if (delay !== undefined) {
          retryCount.current += 1
          retryTimer.current = setTimeout(() => {
            void performSave()
          }, delay)
        }
        return false
      }
    },
    [schedule],
  )

  scheduleRef.current = () => {
    if (!optionsRef.current.enabled && optionsRef.current.enabled !== undefined)
      return
    if (debounceTimer.current) clearTimeout(debounceTimer.current)
    debounceTimer.current = setTimeout(() => {
      void performSave()
    }, debounceMs)
    if (!maxWaitTimer.current) {
      maxWaitTimer.current = setTimeout(() => {
        maxWaitTimer.current = null
        void performSave()
      }, maxWaitMs)
    }
  }

  const markDirty = useCallback(() => {
    if (!optionsRef.current.enabled && optionsRef.current.enabled !== undefined)
      return
    dirtyRef.current = true
    if (savingRef.current) {
      dirtySinceSaveRef.current = true
      return
    }
    setStatus((prev) => (prev === "conflict" ? prev : "dirty"))
    if (status !== "conflict") schedule()
  }, [schedule, status])

  const flush = useCallback(async () => {
    if (!dirtyRef.current) return true
    if (status === "conflict") return false
    return performSave()
  }, [performSave, status])

  const retry = useCallback(async () => {
    retryCount.current = 0
    return performSave()
  }, [performSave])

  const resolveConflict = useCallback(
    async (mode: "reload" | "overwrite") => {
      const c = conflict
      setConflict(null)
      if (mode === "reload") {
        clearTimers()
        dirtyRef.current = false
        dirtySinceSaveRef.current = false
        await optionsRef.current.onReload?.()
        setStatus("clean")
        return
      }
      const base = c?.serverVersion ?? versionRef.current + 1
      versionRef.current = base
      setVersion(base)
      setStatus("dirty")
      await performSave(base)
    },
    [conflict, performSave, clearTimers],
  )

  // Disable → clear timers
  useEffect(() => {
    if (!enabled) clearTimers()
  }, [enabled, clearTimers])

  // Window bindings
  useEffect(() => {
    if (!bindWindowEvents || !enabled) return
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "s") {
        e.preventDefault()
        void flush()
      }
    }
    const onBlur = () => {
      void flush()
    }
    const onVisibility = () => {
      if (document.visibilityState === "hidden") void flush()
    }
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      if (dirtyRef.current || savingRef.current) {
        e.preventDefault()
        e.returnValue = ""
      }
    }
    window.addEventListener("keydown", onKey)
    window.addEventListener("blur", onBlur)
    document.addEventListener("visibilitychange", onVisibility)
    window.addEventListener("beforeunload", onBeforeUnload)
    return () => {
      window.removeEventListener("keydown", onKey)
      window.removeEventListener("blur", onBlur)
      document.removeEventListener("visibilitychange", onVisibility)
      window.removeEventListener("beforeunload", onBeforeUnload)
    }
  }, [bindWindowEvents, enabled, flush])

  useEffect(() => clearTimers, [clearTimers])

  return useMemo(
    () => ({
      status,
      lastSavedAt,
      version,
      error,
      conflict,
      isDirty: dirtyRef.current,
      markDirty,
      flush,
      retry,
      resolveConflict,
    }),
    [
      status,
      lastSavedAt,
      version,
      error,
      conflict,
      markDirty,
      flush,
      retry,
      resolveConflict,
    ],
  )
}

export default useAutosave
