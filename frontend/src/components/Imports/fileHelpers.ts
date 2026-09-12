/** Upload limits mirrored from the API (`MAX_IMPORT_SIZE_MB`). */
export const MAX_IMPORT_BYTES = 50 * 1024 * 1024

export const ACCEPTED_IMPORT_TYPES = "application/pdf,image/*"

const IMAGE_TYPES = new Set([
  "image/png",
  "image/jpeg",
  "image/jpg",
  "image/webp",
  "image/gif",
  "image/bmp",
  "image/tiff",
])

export function isPdf(file: { type: string; name: string }): boolean {
  return (
    file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf")
  )
}

export function isSupportedImport(file: {
  type: string
  name: string
}): boolean {
  return isPdf(file) || IMAGE_TYPES.has(file.type)
}

/** Human-readable size; the API reports bytes. */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  const units = ["KB", "MB", "GB"]
  let value = bytes / 1024
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit += 1
  }
  return `${value < 10 ? value.toFixed(1) : Math.round(value)} ${units[unit]}`
}

/** "Quarterly report.pdf" -> "Quarterly report" */
export function filenameStem(filename: string): string {
  const dot = filename.lastIndexOf(".")
  return (dot > 0 ? filename.slice(0, dot) : filename).trim()
}

/** null when the file is acceptable, otherwise a message to show the user. */
export function rejectionReason(file: File): string | null {
  if (!isSupportedImport(file)) {
    return `“${file.name}” is not a PDF or an image. Accepted: PDF, PNG, JPEG, WebP, GIF, BMP, TIFF.`
  }
  if (file.size > MAX_IMPORT_BYTES) {
    return `“${file.name}” is ${formatBytes(file.size)}. The limit is ${formatBytes(MAX_IMPORT_BYTES)}.`
  }
  return null
}
