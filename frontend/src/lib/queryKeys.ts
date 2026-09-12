/** Central query-key factory so invalidation never relies on hand-typed arrays. */
export const queryKeys = {
  currentUser: ["currentUser"] as const,
  namespaces: {
    all: ["namespaces"] as const,
    list: () => ["namespaces", "list"] as const,
    bySlug: (slug: string) => ["namespaces", "by-slug", slug] as const,
    detail: (id: string) => ["namespaces", id] as const,
    members: (id: string) => ["namespaces", id, "members"] as const,
    tree: (id: string) => ["namespaces", id, "tree"] as const,
  },
  folders: {
    detail: (id: string) => ["folders", id] as const,
  },
  documents: {
    all: ["documents"] as const,
    detail: (id: string) => ["documents", id] as const,
    shares: (id: string) => ["documents", id, "shares"] as const,
    invitations: (id: string) => ["documents", id, "invitations"] as const,
    embeddings: (id: string) => ["documents", id, "embeddings"] as const,
    attachments: (id: string) => ["documents", id, "attachments"] as const,
    recent: () => ["documents", "recent"] as const,
    types: () => ["documents", "types"] as const,
    list: (params: Record<string, unknown>) =>
      ["documents", "list", params] as const,
  },
  shared: ["shared"] as const,
  userLookup: (email: string) => ["users", "lookup", email] as const,
  publicDocument: (identifier: string) =>
    ["public", "document", identifier] as const,
  invitationPreview: (token: string) =>
    ["public", "invitation", token] as const,
  search: (q: string, namespaceId?: string | null) =>
    ["search", q, namespaceId ?? null] as const,
  apiKeys: ["api-keys"] as const,
  health: ["health"] as const,
  workers: ["workers"] as const,
  embeddingSummary: ["embeddings", "summary"] as const,
  attachmentBlob: (id: string) => ["attachments", id, "blob"] as const,
}
