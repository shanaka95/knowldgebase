import type { QueryClient } from "@tanstack/react-query"
import { ReactQueryDevtools } from "@tanstack/react-query-devtools"
import {
  createRootRouteWithContext,
  HeadContent,
  Outlet,
} from "@tanstack/react-router"
import { TanStackRouterDevtools } from "@tanstack/react-router-devtools"
import NotFound from "@/components/Common/NotFound"
import { RouteErrorComponent } from "@/components/Layout/RouteErrorComponent"

export interface RouterContext {
  queryClient: QueryClient
}

export const Route = createRootRouteWithContext<RouterContext>()({
  component: () => (
    <>
      <HeadContent />
      <Outlet />
      <TanStackRouterDevtools position="bottom-right" />
      <ReactQueryDevtools initialIsOpen={false} />
    </>
  ),
  notFoundComponent: () => <NotFound />,
  // The same component the layout uses, rather than a friendlier dead end:
  // an error that reaches the root is the one most in need of saying what it
  // was, and "Oops!" with a Go Home button said nothing anybody could act on.
  errorComponent: RouteErrorComponent,
})
