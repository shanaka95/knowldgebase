import "@fontsource-variable/inter"
import "@fontsource-variable/jetbrains-mono"
import {
  MutationCache,
  QueryCache,
  QueryClient,
  QueryClientProvider,
} from "@tanstack/react-query"
import { createRouter, RouterProvider } from "@tanstack/react-router"
import { AxiosError } from "axios"
import { StrictMode } from "react"
import ReactDOM from "react-dom/client"
import { client } from "./client/client.gen"
import { ThemeProvider } from "./components/theme-provider"
import { Toaster } from "./components/ui/sonner"
import "./index.css"
import { watchForStaleBuild } from "./lib/staleBuild"
import { routeTree } from "./routeTree.gen"

client.setConfig({
  baseURL: import.meta.env.VITE_API_URL ?? "",
  auth: () => localStorage.getItem("access_token") || "",
})

// Only a dead session logs the user out: a 401, or the backend's 403 for a
// token it cannot decode ("Could not validate credentials"). Any other 403
// means "you may not access this resource" and is handled per route.
const isSessionError = (error: Error) => {
  if (!(error instanceof AxiosError) || !error.response) return false
  const { status, data } = error.response
  if (status === 401) return true
  const detail = (data as { detail?: unknown } | undefined)?.detail
  return status === 403 && detail === "Could not validate credentials"
}

const handleApiError = (error: Error) => {
  if (isSessionError(error)) {
    localStorage.removeItem("access_token")
    window.location.href = "/login"
  }
}

const queryClient = new QueryClient({
  queryCache: new QueryCache({
    onError: handleApiError,
  }),
  mutationCache: new MutationCache({
    onError: handleApiError,
  }),
  defaultOptions: {
    queries: {
      staleTime: 10_000,
      retry: (failureCount, error) => {
        if (error instanceof AxiosError) {
          const status = error.response?.status ?? 0
          if (status >= 400 && status < 500) return false
        }
        return failureCount < 2
      },
    },
  },
})

// A deploy can land while somebody is mid-session; the first navigation after
// one asks for a chunk that has been replaced. Registered before the router so
// the very first failed import is caught.
// `import.meta.url` here is the entry chunk's own hashed URL, which is what
// identifies this build. Passed in rather than read inside the helper, where
// it would name that helper's chunk instead.
watchForStaleBuild(import.meta.url)

const router = createRouter({
  routeTree,
  context: { queryClient },
  defaultPreload: "intent",
  defaultPreloadStaleTime: 0,
  defaultPendingMs: 300,
  scrollRestoration: true,
})

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router
  }
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ThemeProvider defaultTheme="system" storageKey="vite-ui-theme">
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
        <Toaster richColors closeButton />
      </QueryClientProvider>
    </ThemeProvider>
  </StrictMode>,
)
