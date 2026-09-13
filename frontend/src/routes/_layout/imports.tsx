import { createFileRoute, redirect } from "@tanstack/react-router"

/**
 * The page this used to be. Kept as a redirect because people bookmark pages
 * and paste links to each other, and a rename is not a reason for either to
 * stop working.
 */
export const Route = createFileRoute("/_layout/imports")({
  beforeLoad: () => {
    throw redirect({ to: "/capture", replace: true })
  },
})
