import { useQuery } from "@tanstack/react-query"
import { useParams } from "@tanstack/react-router"
import { useEffect, useMemo } from "react"

import type { NamespacePublic } from "@/client"
import { namespaceBySlugQuery, namespacesQuery } from "@/queries/namespaces"

export const LAST_NAMESPACE_KEY = "kb:lastNamespaceSlug"

export function readLastNamespaceSlug(): string | null {
  try {
    return localStorage.getItem(LAST_NAMESPACE_KEY)
  } catch {
    return null
  }
}

export function rememberNamespaceSlug(slug: string) {
  try {
    localStorage.setItem(LAST_NAMESPACE_KEY, slug)
  } catch {
    /* ignore */
  }
}

export function useNamespaces() {
  return useQuery(namespacesQuery())
}

export function canEditNamespace(ns: NamespacePublic | null | undefined) {
  return ns?.my_role === "editor" || ns?.my_role === "admin"
}

export function canAdminNamespace(ns: NamespacePublic | null | undefined) {
  return ns?.my_role === "admin"
}

/**
 * The namespace the sidebar shows: URL param → last visited → first available.
 */
export function useActiveNamespace() {
  const params = useParams({ strict: false }) as { namespaceSlug?: string }
  const { data: namespaces, isPending } = useNamespaces()
  const list = namespaces?.data ?? []
  const slug = params.namespaceSlug
  const inList = slug ? list.some((n) => n.slug === slug) : true

  // A space the user only holds document shares in is not part of "my
  // spaces" but is still readable; resolve it by slug so the shell renders.
  const { data: bySlug } = useQuery({
    ...namespaceBySlugQuery(slug ?? ""),
    enabled: Boolean(slug) && !isPending && !inList,
    retry: false,
  })

  const active = useMemo<NamespacePublic | null>(() => {
    if (slug) {
      const fromUrl = list.find((n) => n.slug === slug)
      if (fromUrl) return fromUrl
      if (bySlug && bySlug.slug === slug) return bySlug
    }
    if (list.length === 0) return null
    const last = readLastNamespaceSlug()
    if (last) {
      const fromStorage = list.find((n) => n.slug === last)
      if (fromStorage) return fromStorage
    }
    return list[0]
  }, [list, slug, bySlug])

  useEffect(() => {
    if (params.namespaceSlug && active?.slug === params.namespaceSlug) {
      rememberNamespaceSlug(active.slug)
    }
  }, [params.namespaceSlug, active])

  return { active, namespaces: list, isPending }
}
