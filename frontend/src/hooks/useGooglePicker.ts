import { DataSourcesService } from "@/client"

/**
 * Google's own file picker, which is the only way `drive.file` can work.
 *
 * The scope grants this application nothing until somebody chooses a specific
 * file here, and then only that file: we cannot list a Drive, search it, or
 * reach anything that was not handed over. That is the privacy property worth
 * having, and it is also why there is no PlusGPT-built Drive browser to
 * maintain - Google's picker is the consent.
 *
 * The access token it is given is minutes long and fetched per use rather than
 * held, so a tab left open overnight has nothing live in it.
 */

const GAPI_SRC = "https://apis.google.com/js/api.js"

/** What a page can actually be made from. */
export const PICKABLE_MIME_TYPES = [
  "application/pdf",
  "image/jpeg",
  "image/png",
  "image/webp",
  "image/gif",
  "image/tiff",
  "image/heic",
  "image/heif",
].join(",")

export interface PickedFile {
  file_id: string
  name: string
  mime_type: string
  /** Bytes, as Google's picker reports them. 0 when it does not say. */
  size: number
}

/**
 * The most a single file may be, matching `MAX_IMPORT_SIZE_MB` on the server.
 *
 * Checked here as well as there because the picker already knows the size: a
 * 200MB file can be refused the instant it is chosen, instead of after the
 * server has fetched it from Google to find out.
 */
export const MAX_FILE_MB = 50
export const MAX_FILE_BYTES = MAX_FILE_MB * 1024 * 1024

export function tooLarge(files: PickedFile[]): PickedFile[] {
  return files.filter((f) => f.size > MAX_FILE_BYTES)
}

declare global {
  interface Window {
    gapi?: {
      load: (name: string, cb: () => void) => void
    }
    google?: {
      picker?: Record<string, any>
    }
  }
}

let scriptPromise: Promise<void> | null = null

function loadScript(): Promise<void> {
  if (window.gapi) return Promise.resolve()
  if (scriptPromise) return scriptPromise
  scriptPromise = new Promise<void>((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>(
      `script[src="${GAPI_SRC}"]`,
    )
    const script = existing ?? document.createElement("script")
    script.src = GAPI_SRC
    script.async = true
    script.onload = () => resolve()
    script.onerror = () => {
      // Let a later attempt retry rather than caching the failure forever: a
      // flaky network on first click should not disable the button for good.
      scriptPromise = null
      reject(new Error("Google's file picker could not be loaded."))
    }
    if (!existing) document.head.appendChild(script)
  })
  return scriptPromise
}

function loadPicker(): Promise<void> {
  return new Promise((resolve, reject) => {
    if (window.google?.picker) return resolve()
    if (!window.gapi)
      return reject(new Error("Google's picker is unavailable."))
    window.gapi.load("picker", () => resolve())
  })
}

/**
 * Open the picker and resolve with what was chosen. Resolves empty if the
 * person cancelled, which is not an error and should not be reported as one.
 */
export async function pickFromGoogleDrive(): Promise<PickedFile[]> {
  const config = (await DataSourcesService.googleDrivePicker()).data

  await loadScript()
  await loadPicker()
  const picker = window.google?.picker
  if (!picker) throw new Error("Google's picker is unavailable.")

  return new Promise<PickedFile[]>((resolve) => {
    const view = new picker.DocsView(picker.ViewId.DOCS)
    view.setMimeTypes(PICKABLE_MIME_TYPES)
    view.setIncludeFolders(true)
    view.setSelectFolderEnabled(false)

    const built = new picker.PickerBuilder()
      .setAppId(config.client_id.split("-")[0] ?? "")
      .setOAuthToken(config.access_token)
      .setDeveloperKey(config.api_key)
      .addView(view)
      .enableFeature(picker.Feature.MULTISELECT_ENABLED)
      .setCallback((data: any) => {
        if (data.action === picker.Action.PICKED) {
          resolve(
            (data.docs ?? []).map((doc: any) => ({
              file_id: String(doc.id),
              name: String(doc.name ?? "file"),
              mime_type: String(doc.mimeType ?? ""),
              size: Number(doc.sizeBytes ?? 0) || 0,
            })),
          )
        } else if (data.action === picker.Action.CANCEL) {
          resolve([])
        }
      })
      .build()

    built.setVisible(true)
  })
}
