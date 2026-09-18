/** Central query-key factory so invalidation never relies on hand-typed arrays. */
export const queryKeys = {
  currentUser: ["currentUser"] as const,
  namespaces: {
    all: ["namespaces"] as const,
    list: () => ["namespaces", "list"] as const,
    bySlug: (slug: string) => ["namespaces", "by-slug", slug] as const,
    detail: (id: string) => ["namespaces", id] as const,
    members: (id: string) => ["namespaces", id, "members"] as const,
    invitations: (id: string) => ["namespaces", id, "invitations"] as const,
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
    versions: (id: string) => ["documents", id, "versions"] as const,
    version: (id: string, version: number) =>
      ["documents", id, "versions", version] as const,
    languages: (id: string) => ["documents", id, "languages"] as const,
    translation: (id: string, version: number, language: string) =>
      ["documents", id, "translations", version, language] as const,
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
  askConversations: {
    all: ["ask", "conversations"] as const,
    list: () => ["ask", "conversations", "list"] as const,
    detail: (id: string) => ["ask", "conversations", id] as const,
  },
  searchSuggestions: () => ["search", "suggestions"] as const,
  // The administration area hand-typed its keys in three different places; new
  // work joins the factory so invalidation cannot drift.
  admin: {
    all: ["admin"] as const,
    groups: () => ["admin", "user-groups"] as const,
    limits: () => ["admin", "limits"] as const,
    users: (params: Record<string, unknown> = {}) =>
      ["admin", "users", params] as const,
    usage: (params: Record<string, unknown> = {}) =>
      ["admin", "usage", params] as const,
    usageModels: (params: Record<string, unknown> = {}) =>
      ["admin", "usage", "models", params] as const,
    marketing: {
      all: ["admin", "marketing"] as const,
      settings: () => ["admin", "marketing", "settings"] as const,
      template: () => ["admin", "marketing", "template"] as const,
      contacts: (params: Record<string, unknown> = {}) =>
        ["admin", "marketing", "contacts", params] as const,
      contactIds: (params: Record<string, unknown> = {}) =>
        ["admin", "marketing", "contact-ids", params] as const,
      campaigns: () => ["admin", "marketing", "campaigns"] as const,
      campaign: (id: string) =>
        ["admin", "marketing", "campaigns", id] as const,
      deliveries: (id: string) =>
        ["admin", "marketing", "campaigns", id, "deliveries"] as const,
    },
  },
  dataSources: {
    all: ["data-sources"] as const,
  },
  notes: {
    all: ["notes"] as const,
    list: (documentId: string) => ["documents", documentId, "notes"] as const,
  },
  usage: {
    all: ["usage"] as const,
    mine: (params: Record<string, unknown> = {}) =>
      ["usage", "me", params] as const,
    credits: () => ["usage", "credits"] as const,
    grants: (userId: string) => ["admin", "credits", userId, "grants"] as const,
  },
  apiKeys: ["api-keys"] as const,
  health: ["health"] as const,
  workers: ["workers"] as const,
  embeddingSummary: ["embeddings", "summary"] as const,
  attachmentBlob: (id: string) => ["attachments", id, "blob"] as const,
}
