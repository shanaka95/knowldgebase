import {
  queryOptions,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query"
import { CheckCircle2, Loader2, QrCode, Smartphone } from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"

import { AdminChannelsService } from "@/client"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"

const pairingKey = ["admin", "channels", "whatsapp", "pairing"] as const

/**
 * Polls only while a pairing attempt is live.
 *
 * WhatsApp reissues its QR every twenty seconds or so, and the scan happens on
 * a phone, so the dialog has to notice both on its own.
 */
function pairingQuery(active: boolean) {
  return queryOptions({
    queryKey: pairingKey,
    queryFn: async () => (await AdminChannelsService.readPairing()).data,
    refetchInterval: active ? 2_000 : false,
    refetchIntervalInBackground: false,
  })
}

export function WhatsAppPairing() {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const { data } = useQuery(pairingQuery(open))

  const state = data?.state ?? "unknown"
  const paired = state === "paired" || state === "connected"

  const start = useMutation({
    mutationFn: async () => AdminChannelsService.startPairing(),
    onSuccess: () => {
      setOpen(true)
      void queryClient.invalidateQueries({ queryKey: pairingKey })
    },
    onError: (error: { body?: { detail?: string } }) =>
      toast.error(error.body?.detail ?? "Could not start pairing"),
  })

  const cancel = useMutation({
    mutationFn: async () => AdminChannelsService.stopPairing(),
    onSettled: () => {
      setOpen(false)
      void queryClient.invalidateQueries({ queryKey: pairingKey })
    },
  })

  const signOut = useMutation({
    mutationFn: async () =>
      AdminChannelsService.stopPairing({ query: { forget: true } }),
    onSuccess: () => {
      toast.success("Signing out of WhatsApp")
      void queryClient.invalidateQueries({ queryKey: pairingKey })
    },
  })

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        {paired ? (
          <>
            <span className="flex items-center gap-1.5 text-sm text-muted-foreground">
              <CheckCircle2 className="size-4 text-emerald-600" />
              Paired
              {data?.account ? ` as ${data.account}` : ""}
            </span>
            <Button
              variant="outline"
              size="sm"
              onClick={() => signOut.mutate()}
              disabled={signOut.isPending}
            >
              Sign out
            </Button>
          </>
        ) : (
          <Button
            variant="outline"
            size="sm"
            onClick={() => start.mutate()}
            disabled={start.isPending}
          >
            <QrCode />
            Pair with WhatsApp
          </Button>
        )}
      </div>
      <p className="text-xs text-muted-foreground">
        The bridge signs in the way WhatsApp Web does — by scanning a QR code
        with the phone whose account the agent will use. There is no token to
        paste in.
      </p>

      <Dialog
        open={open}
        onOpenChange={(next) => {
          if (!next) cancel.mutate()
          else setOpen(true)
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Pair with WhatsApp</DialogTitle>
            <DialogDescription>
              On the phone:{" "}
              <strong>Settings → Linked devices → Link a device</strong>, then
              scan this code.
            </DialogDescription>
          </DialogHeader>

          <PairingBody
            state={state}
            qrSvg={data?.qr_svg}
            detail={data?.detail}
          />

          <DialogFooter>
            <Button variant="outline" onClick={() => cancel.mutate()}>
              {state === "connected" ? "Done" : "Cancel"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

function PairingBody({
  state,
  qrSvg,
  detail,
}: {
  state: string
  qrSvg?: string | null
  detail?: string | null
}) {
  if (state === "connected" || state === "paired") {
    return (
      <div className="flex flex-col items-center gap-3 py-6">
        <CheckCircle2 className="size-10 text-emerald-600" />
        <p className="text-center font-medium">WhatsApp is connected.</p>
        <p className="text-center text-sm text-muted-foreground">
          Users can now connect their own WhatsApp to an agent from the Agents
          page.
        </p>
      </div>
    )
  }

  if (state === "error" || state === "unavailable") {
    return (
      <Alert variant="destructive">
        <AlertDescription>
          {detail ?? "Pairing could not be started."}
        </AlertDescription>
      </Alert>
    )
  }

  if (state === "qr" && qrSvg) {
    return (
      <div className="flex flex-col items-center gap-3">
        {/*
          The QR is rendered server-side and arrives as an SVG. It is generated
          from the bridge's own payload by our backend, not supplied by a user,
          and it is the only way to show something scannable without shipping a
          QR encoder to the browser.
        */}
        <div
          className="w-full max-w-[260px] rounded-lg bg-white p-3 [&_svg]:h-auto [&_svg]:w-full"
          // biome-ignore lint/security/noDangerouslySetInnerHtml: server-generated SVG, see above
          dangerouslySetInnerHTML={{ __html: qrSvg }}
        />
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <Smartphone className="size-4" />
          Waiting for the scan… the code refreshes on its own.
        </p>
      </div>
    )
  }

  return (
    <div className="flex flex-col items-center gap-3 py-8">
      <Loader2 className="size-6 animate-spin text-muted-foreground" />
      <p className="text-sm text-muted-foreground">
        {state === "starting"
          ? "Starting the bridge…"
          : "Waiting for a code from the gateway…"}
      </p>
    </div>
  )
}
