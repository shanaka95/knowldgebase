import { Link, useMatches } from "@tanstack/react-router"
import { Fragment } from "react"

import {
  Breadcrumb,
  BreadcrumbEllipsis,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { type Crumb, useCrumbsStore } from "@/lib/breadcrumbs"

function crumbsFromMatches(matches: ReturnType<typeof useMatches>): Crumb[] {
  const crumbs: Crumb[] = []
  for (const match of matches) {
    const loaderCrumbs = (match.loaderData as { crumbs?: Crumb[] } | undefined)
      ?.crumbs
    if (Array.isArray(loaderCrumbs)) {
      crumbs.push(...loaderCrumbs)
      continue
    }
    const staticCrumb = match.staticData?.crumb
    if (staticCrumb) {
      crumbs.push({ label: staticCrumb, to: match.pathname })
    }
  }
  return crumbs
}

const MAX_VISIBLE = 4

export function Breadcrumbs() {
  const matches = useMatches()
  const override = useCrumbsStore((s) => s.override)
  const crumbs = override ?? crumbsFromMatches(matches)

  if (crumbs.length === 0) return null

  let visible: Crumb[] = crumbs
  let collapsed: Crumb[] = []
  if (crumbs.length > MAX_VISIBLE) {
    visible = [crumbs[0], ...crumbs.slice(-2)]
    collapsed = crumbs.slice(1, -2)
  }

  return (
    <Breadcrumb className="min-w-0">
      <BreadcrumbList className="flex-nowrap">
        {visible.map((crumb, index) => {
          const isLast = index === visible.length - 1
          const showEllipsisAfter = collapsed.length > 0 && index === 0
          return (
            <Fragment key={`${crumb.label}-${index}`}>
              <BreadcrumbItem className="min-w-0">
                {isLast || !crumb.to ? (
                  <BreadcrumbPage className="truncate max-w-[16rem] inline-flex items-center gap-1.5">
                    {crumb.icon}
                    <span className="truncate">{crumb.label}</span>
                  </BreadcrumbPage>
                ) : (
                  <BreadcrumbLink asChild>
                    <Link
                      to={crumb.to}
                      className="truncate max-w-[12rem] inline-flex items-center gap-1.5"
                    >
                      {crumb.icon}
                      <span className="truncate">{crumb.label}</span>
                    </Link>
                  </BreadcrumbLink>
                )}
              </BreadcrumbItem>
              {showEllipsisAfter && (
                <>
                  <BreadcrumbSeparator />
                  <BreadcrumbItem>
                    <DropdownMenu>
                      <DropdownMenuTrigger
                        className="flex items-center gap-1"
                        aria-label="Show hidden breadcrumbs"
                      >
                        <BreadcrumbEllipsis className="size-4" />
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="start">
                        {collapsed.map((c, i) => (
                          <DropdownMenuItem key={`${c.label}-${i}`} asChild>
                            {c.to ? (
                              <Link to={c.to}>{c.label}</Link>
                            ) : (
                              <span>{c.label}</span>
                            )}
                          </DropdownMenuItem>
                        ))}
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </BreadcrumbItem>
                </>
              )}
              {!isLast && <BreadcrumbSeparator />}
            </Fragment>
          )
        })}
      </BreadcrumbList>
    </Breadcrumb>
  )
}
