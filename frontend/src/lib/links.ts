/** URL helpers so every feature links to the same place. */
export const links = {
  space: (slug: string) => `/s/${slug}`,
  folder: (slug: string, folderId: string) => `/s/${slug}/f/${folderId}`,
  document: (slug: string, documentId: string) => `/s/${slug}/d/${documentId}`,
  spaceSettings: (slug: string) => `/s/${slug}/settings`,
}

export function absoluteUrl(path: string) {
  return `${window.location.origin}${path}`
}
