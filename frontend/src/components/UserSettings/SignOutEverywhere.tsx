import { useMutation } from "@tanstack/react-query"

import { LoginService } from "@/client"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { LoadingButton } from "@/components/ui/loading-button"
import useAuth from "@/hooks/useAuth"
import useCustomToast from "@/hooks/useCustomToast"
import { handleError } from "@/utils"

const SignOutEverywhere = () => {
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const { logout } = useAuth()

  const mutation = useMutation({
    mutationFn: async () => (await LoginService.signOutEverywhere()).data,
    onSuccess: (data) => {
      showSuccessToast(data.message)
      // This session was ended too, so the token in hand is already dead.
      logout()
    },
    onError: handleError.bind(showErrorToast),
  })

  return (
    <div className="max-w-md mt-8 rounded-lg border p-4">
      <h3 className="font-semibold">Sign out everywhere</h3>
      <p className="mt-1 text-sm text-muted-foreground">
        End every session on this account, on every device. This one included —
        you will have to sign in again.
      </p>

      <Dialog>
        <DialogTrigger asChild>
          <Button
            variant="outline"
            className="mt-3"
            data-testid="sign-out-everywhere"
          >
            Sign out everywhere
          </Button>
        </DialogTrigger>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Confirmation Required</DialogTitle>
            <DialogDescription>
              Every session on this account will end, including this one. You
              will be sent back to the login page.
            </DialogDescription>
          </DialogHeader>

          <DialogFooter className="mt-4">
            <DialogClose asChild>
              <Button variant="outline" disabled={mutation.isPending}>
                Cancel
              </Button>
            </DialogClose>
            <LoadingButton
              type="button"
              loading={mutation.isPending}
              onClick={() => mutation.mutate()}
              data-testid="confirm-sign-out-everywhere"
            >
              Sign out everywhere
            </LoadingButton>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

export default SignOutEverywhere
