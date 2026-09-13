import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { CheckCircle2, CircleDashed } from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"

import { AdminChannelsService, type ChannelConfigPublic } from "@/client"
import { ChannelIcon } from "@/components/Common/ChannelIcon"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { Switch } from "@/components/ui/switch"
import { adminChannelsQuery, agentKeys, channelLabel } from "@/queries/agents"
import { WhatsAppPairing } from "./WhatsAppPairing"

/** What each credential field is, in the words an admin would look for. */
const FIELD_LABELS: Record<string, string> = {
  bot_token: "Bot token",
  app_token: "App token",
  signing_secret: "Signing secret",
  access_token: "Access token",
  phone_number_id: "Phone number ID",
  verify_token: "Webhook verify token",
}

const HANDLE_HINTS: Record<string, string> = {
  telegram: "@your_bot",
  whatsapp: "+44 7700 900000",
  slack: "@PlusGPT",
  discord: "PlusGPT#0001",
}

export function ChannelsPanel() {
  const { data, isPending } = useQuery(adminChannelsQuery())

  if (isPending || !data) {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-muted-foreground">
        A channel appears on people's agents once it is configured and switched
        on. Credentials are encrypted and never shown again after saving.
      </p>
      {data.data.map((channel) => (
        <ChannelCard key={channel.channel_type} channel={channel} />
      ))}
    </div>
  )
}

function ChannelCard({ channel }: { channel: ChannelConfigPublic }) {
  const queryClient = useQueryClient()
  const [values, setValues] = useState<Record<string, string>>({})
  const [handle, setHandle] = useState(channel.public_handle ?? "")
  const [transport, setTransport] = useState(channel.transport ?? "cloud_api")

  const save = useMutation({
    mutationFn: async (body: Record<string, unknown>) =>
      AdminChannelsService.updateChannel({
        path: { channel_type: channel.channel_type },
        body: body as never,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: agentKeys.adminChannels(),
      })
      setValues({})
      toast.success(`${channelLabel(channel.channel_type)} saved`)
    },
    onError: (error: { body?: { detail?: string } }) =>
      toast.error(error.body?.detail ?? "Could not save this channel"),
  })

  const isWhatsApp = channel.channel_type === "whatsapp"

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <CardTitle className="flex items-center gap-2">
              <ChannelIcon channel={channel.channel_type} className="size-5" />
              {channelLabel(channel.channel_type)}
              {channel.configured ? (
                <Badge variant="secondary" className="gap-1">
                  <CheckCircle2 className="size-3" />
                  Configured
                </Badge>
              ) : (
                <Badge variant="outline" className="gap-1">
                  <CircleDashed className="size-3" />
                  Not configured
                </Badge>
              )}
            </CardTitle>
            <CardDescription>
              {channel.enabled
                ? "Offered to everyone on their agent page."
                : "Hidden from users until it is switched on."}
            </CardDescription>
          </div>
          <div className="flex items-center gap-2">
            <Label
              htmlFor={`enabled-${channel.channel_type}`}
              className="text-sm"
            >
              Enabled
            </Label>
            <Switch
              id={`enabled-${channel.channel_type}`}
              checked={channel.enabled}
              onCheckedChange={(enabled) => save.mutate({ enabled })}
            />
          </div>
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {isWhatsApp && (
          <div className="flex flex-col gap-2">
            <Label>Transport</Label>
            <Select
              value={transport}
              onValueChange={(value) => {
                setTransport(value as typeof transport)
                save.mutate({ transport: value })
              }}
            >
              <SelectTrigger className="w-full sm:w-80">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="cloud_api">
                  Cloud API — official, scales, priced per conversation
                </SelectItem>
                <SelectItem value="bridge">
                  Local bridge — QR-paired, free, unofficial
                </SelectItem>
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">
              The bridge signs in as an ordinary WhatsApp account. It is against
              WhatsApp's terms, and a ban would take every user's agent down at
              once — fine for testing, risky in production.
            </p>
          </div>
        )}

        {isWhatsApp && transport === "bridge" && <WhatsAppPairing />}

        <div className="flex flex-col gap-2">
          <Label htmlFor={`handle-${channel.channel_type}`}>
            Public handle
          </Label>
          <Input
            id={`handle-${channel.channel_type}`}
            value={handle}
            onChange={(e) => setHandle(e.target.value)}
            placeholder={HANDLE_HINTS[channel.channel_type] ?? ""}
            className="w-full sm:w-80"
          />
          <p className="text-xs text-muted-foreground">
            Shown to users so they know where to send their connection code.
          </p>
        </div>

        {channel.required_fields.length > 0 && (
          <div className="grid gap-3 sm:grid-cols-2">
            {channel.required_fields.map((field) => {
              const isSet = channel.present_fields.includes(field)
              return (
                <div key={field} className="flex min-w-0 flex-col gap-2">
                  <Label htmlFor={`${channel.channel_type}-${field}`}>
                    {FIELD_LABELS[field] ?? field}
                  </Label>
                  <Input
                    id={`${channel.channel_type}-${field}`}
                    type="password"
                    autoComplete="off"
                    value={values[field] ?? ""}
                    onChange={(e) =>
                      setValues((v) => ({ ...v, [field]: e.target.value }))
                    }
                    placeholder={isSet ? "•••••••• (saved)" : "Not set"}
                  />
                </div>
              )
            })}
          </div>
        )}

        <div className="flex flex-wrap gap-2">
          <Button
            onClick={() =>
              save.mutate({
                public_handle: handle,
                ...(Object.keys(values).length ? { credentials: values } : {}),
              })
            }
            disabled={save.isPending}
          >
            Save
          </Button>
          {channel.configured && (
            <Button
              variant="outline"
              onClick={() => {
                void AdminChannelsService.clearChannel({
                  path: { channel_type: channel.channel_type },
                }).then(() => {
                  void queryClient.invalidateQueries({
                    queryKey: agentKeys.adminChannels(),
                  })
                  toast.success("Credentials cleared")
                })
              }}
            >
              Clear credentials
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
