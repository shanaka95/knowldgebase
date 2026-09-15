import { EllipsisVertical, SlidersHorizontal } from "lucide-react"
import { useState } from "react"

import type { AdminUserPublic } from "@/client"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import useAuth from "@/hooks/useAuth"
import DeleteUser from "./DeleteUser"
import EditUser from "./EditUser"
import { UserAssignmentDialog } from "./UserAssignmentDialog"

interface UserActionsMenuProps {
  user: AdminUserPublic
}

export const UserActionsMenu = ({ user }: UserActionsMenuProps) => {
  const [open, setOpen] = useState(false)
  const [assigning, setAssigning] = useState(false)
  const { user: currentUser } = useAuth()

  if (user.id === currentUser?.id) {
    return null
  }

  return (
    <DropdownMenu open={open} onOpenChange={setOpen}>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon">
          <EllipsisVertical />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <EditUser user={user} onSuccess={() => setOpen(false)} />
        <DropdownMenuItem
          // The dropdown would close and unmount the dialog with it.
          onSelect={(e) => e.preventDefault()}
          onClick={() => setAssigning(true)}
          data-testid="edit-assignment"
        >
          <SlidersHorizontal className="size-4" />
          Group and limits
        </DropdownMenuItem>
        <DeleteUser id={user.id} onSuccess={() => setOpen(false)} />
      </DropdownMenuContent>

      {assigning && (
        <UserAssignmentDialog
          user={user}
          open={assigning}
          onOpenChange={(next) => {
            setAssigning(next)
            if (!next) setOpen(false)
          }}
        />
      )}
    </DropdownMenu>
  )
}
