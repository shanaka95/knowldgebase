import { NotFoundState } from "@/components/Layout/NotFoundState"

export function DocumentNotFound() {
  return (
    <NotFoundState
      title="Page not found"
      description="This page may have been moved or deleted, or you no longer have access to it."
    />
  )
}

export default DocumentNotFound
