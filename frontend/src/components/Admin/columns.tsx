import type { ColumnDef } from "@tanstack/react-table"

import type { AdminUserPublic } from "@/client"
import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"
import { UserActionsMenu } from "./UserActionsMenu"

export type UserTableData = AdminUserPublic & {
  isCurrentUser: boolean
}

/** Which tier a limit came from, when it is worth saying. */
function limitSource(user: AdminUserPublic, key: string) {
  return (user.limits ?? []).find((limit) => limit.key === key)?.source
}

export const columns: ColumnDef<UserTableData>[] = [
  {
    accessorKey: "full_name",
    header: "Full Name",
    cell: ({ row }) => {
      const fullName = row.original.full_name
      return (
        <div className="flex items-center gap-2">
          <span
            className={cn("font-medium", !fullName && "text-muted-foreground")}
          >
            {fullName || "N/A"}
          </span>
          {row.original.isCurrentUser && (
            <Badge variant="outline" className="text-xs">
              You
            </Badge>
          )}
        </div>
      )
    },
  },
  {
    accessorKey: "email",
    header: "Email",
    cell: ({ row }) => (
      <span className="text-muted-foreground">{row.original.email}</span>
    ),
  },
  {
    accessorKey: "is_superuser",
    header: "Role",
    cell: ({ row }) => (
      <Badge variant={row.original.is_superuser ? "default" : "secondary"}>
        {row.original.is_superuser ? "Superuser" : "User"}
      </Badge>
    ),
  },
  {
    accessorKey: "is_active",
    header: "Status",
    cell: ({ row }) => (
      <div className="flex items-center gap-2">
        <span
          className={cn(
            "size-2 rounded-full",
            row.original.is_active ? "bg-green-500" : "bg-gray-400",
          )}
        />
        <span className={row.original.is_active ? "" : "text-muted-foreground"}>
          {row.original.is_active ? "Active" : "Inactive"}
        </span>
      </div>
    ),
  },
  {
    id: "group",
    header: "Group",
    cell: ({ row }) => {
      const group = row.original.group
      return (
        <span
          className={cn("text-sm", !group && "text-muted-foreground")}
          data-testid="user-group"
        >
          {group ? group.name : "Default"}
        </span>
      )
    },
  },
  {
    id: "pages",
    header: "Pages",
    cell: ({ row }) => {
      const user = row.original
      const overridden = limitSource(user, "max_pages") === "user"
      return (
        <span className="flex items-center gap-1.5" data-testid="user-pages">
          <span className="text-sm tabular-nums">
            {user.pages_used ?? 0} / {user.max_pages ?? 0}
          </span>
          {overridden && (
            <Badge variant="outline" className="text-xs">
              Override
            </Badge>
          )}
        </span>
      )
    },
  },
  {
    id: "actions",
    header: () => <span className="sr-only">Actions</span>,
    cell: ({ row }) => (
      <div className="flex justify-end">
        <UserActionsMenu user={row.original} />
      </div>
    ),
  },
]
