import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, useNavigate } from "@tanstack/react-router"
import {
  Check,
  Copy,
  ExternalLink,
  Loader2,
  MessageSquare,
  Trash2,
  Unplug,
} from "lucide-react"
import { useEffect, useState } from "react"
import { toast } from "sonner"

import { AgentsService } from "@/client"
import { PageContainer, PageHeader } from "@/components/Layout/PageContainer"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Skeleton } from "@/components/ui/skeleton"
import { Textarea } from "@/components/ui/textarea"
import {
  agentChannelsQuery,
  agentKeys,
  agentQuery,
  channelLabel,
} from "@/queries/agents"

export const Route = createFileRoute("/_layout/agents/$agentId")({
  component: AgentDetailPage,
  staticData: { crumb: "Agent" },
  head: () => ({ meta: [{ title: "Agent - PlusGPT" }] }),
})

function AgentDetailPage() {
  const { agentId } = Route.useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  // While a code is outstanding the connection lands from another device, so
  // the page has to watch for it rather than wait for an interaction here.
  const [awaitingLink, setAwaitingLink] = useState(false)
  const { data: agent, isPending } = useQuery(
    agentQuery(agentId, { poll: awaitingLink }),
  )
  const { data: channels } = useQuery(agentChannelsQuery(agentId))

  const connectedCount = agent?.connections.length ?? 0
  useEffect(() => {
    if (awaitingLink && connectedCount > 0) setAwaitingLink(false)
  }, [awaitingLink, connectedCount])

  const remove = useMutation({
    mutationFn: async () =>
      AgentsService.deleteAgent({ path: { agent_id: agentId } }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: agentKeys.all })
      toast.success("Agent deleted")
      void navigate({ to: "/agents" })
    },
  })

  if (isPending || !agent) {
    return (
      <PageContainer className="flex flex-col gap-6">
        <Skeleton className="h-16 w-full" />
        <Skeleton className="h-64 w-full" />
      </PageContainer>
    )
  }

  const available = channels?.data ?? []
  const connectedTypes = new Set(agent.connections.map((c) => c.channel_type))

  return (
    <PageContainer className="flex flex-col gap-6">
      <PageHeader
        title={agent.name}
        description="Message this agent from any channel you connect. It reads and writes your knowledge base, and nobody else's."
        actions={<DeleteAgentButton onConfirm={() => remove.mutate()} />}
      />

      {agent.status !== "ready" && agent.status_detail && (
        <Card className="border-destructive/40">
          <CardContent className="text-sm text-destructive">
            {agent.status_detail}
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Channels</CardTitle>
          <CardDescription>
            Where you can talk to this agent. Each channel account connects to
            one agent only.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          {available.length === 0 && agent.connections.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No channels are available yet. An administrator enables them under
              Admin → Channels.
            </p>
          ) : null}

          {agent.connections.map((connection) => (
            <div
              key={connection.id}
              className="flex flex-wrap items-center justify-between gap-3 rounded-lg border p-3"
            >
              <div className="flex min-w-0 items-center gap-3">
                <MessageSquare className="size-4 shrink-0 text-muted-foreground" />
                <div className="min-w-0">
                  <p className="font-medium">
                    {channelLabel(connection.channel_type)}
                  </p>
                  <p className="truncate text-sm text-muted-foreground">
                    {connection.display_name
                      ? `${connection.display_name} · ${connection.identity_hint}`
                      : connection.identity_hint}
                  </p>
                </div>
                <Badge variant="secondary">Connected</Badge>
              </div>
              <DisconnectButton
                agentId={agentId}
                connectionId={connection.id}
                channel={channelLabel(connection.channel_type)}
              />
            </div>
          ))}

          {available
            .filter((channel) => !connectedTypes.has(channel.channel_type))
            .map((channel) => (
              <ConnectRow
                key={channel.channel_type}
                agentId={agentId}
                channelType={channel.channel_type}
                onAwaiting={() => setAwaitingLink(true)}
              />
            ))}
        </CardContent>
      </Card>

      <PersonaCard agent={agent} />
    </PageContainer>
  )
}

function ConnectRow({
  agentId,
  channelType,
  onAwaiting,
}: {
  agentId: string
  channelType: string
  onAwaiting: () => void
}) {
  const [code, setCode] = useState<{
    code: string
    instructions: string
    deep_link?: string | null
  } | null>(null)

  const issue = useMutation({
    mutationFn: async () =>
      (
        await AgentsService.createLinkCode({
          path: { agent_id: agentId },
          body: { channel_type: channelType as never },
        })
      ).data,
    onSuccess: (data) => {
      setCode(data)
      onAwaiting()
    },
    onError: (error: { body?: { detail?: string } }) =>
      toast.error(error.body?.detail ?? "Could not start the connection"),
  })

  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-dashed p-3">
        <div className="flex items-center gap-3">
          <MessageSquare className="size-4 shrink-0 text-muted-foreground" />
          <p className="font-medium">{channelLabel(channelType)}</p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => issue.mutate()}
          disabled={issue.isPending}
        >
          Connect
        </Button>
      </div>

      <Dialog open={code !== null} onOpenChange={() => setCode(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Connect {channelLabel(channelType)}</DialogTitle>
            <DialogDescription>{code?.instructions}</DialogDescription>
          </DialogHeader>
          {code && (
            <div className="flex flex-col gap-4">
              <CodeBox code={code.code} />
              {code.deep_link && (
                <Button asChild variant="outline">
                  <a
                    href={code.deep_link}
                    target="_blank"
                    rel="noreferrer noopener"
                  >
                    <ExternalLink />
                    Open {channelLabel(channelType)}
                  </a>
                </Button>
              )}
              <p className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="size-4 animate-spin" />
                Waiting for your message… this closes on its own once it
                arrives.
              </p>
              <p className="text-xs text-muted-foreground">
                The code works once and expires shortly. Anyone who has it could
                connect their account to this agent, so do not share it.
              </p>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </>
  )
}

function CodeBox({ code }: { code: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <div className="flex items-center gap-2">
      <code className="flex-1 overflow-x-auto rounded-md bg-muted px-3 py-2 font-mono text-lg tracking-wider">
        {code}
      </code>
      <Button
        variant="outline"
        size="icon"
        onClick={() => {
          void navigator.clipboard.writeText(code)
          setCopied(true)
          setTimeout(() => setCopied(false), 1500)
        }}
        aria-label="Copy code"
      >
        {copied ? <Check /> : <Copy />}
      </Button>
    </div>
  )
}

function DisconnectButton({
  agentId,
  connectionId,
  channel,
}: {
  agentId: string
  connectionId: string
  channel: string
}) {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)

  const disconnect = useMutation({
    mutationFn: async () =>
      AgentsService.deleteConnection({
        path: { agent_id: agentId, connection_id: connectionId },
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: agentKeys.all })
      toast.success(`${channel} disconnected`)
      setOpen(false)
    },
  })

  return (
    <>
      <Button variant="ghost" size="sm" onClick={() => setOpen(true)}>
        <Unplug />
        Disconnect
      </Button>
      <AlertDialog open={open} onOpenChange={setOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Disconnect {channel}?</AlertDialogTitle>
            <AlertDialogDescription>
              Messages from that account will stop reaching this agent
              immediately. Your pages and documents are untouched, and you can
              connect it again later.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={() => disconnect.mutate()}>
              Disconnect
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}

function PersonaCard({
  agent,
}: {
  agent: { id: string; name: string; persona?: string | null }
}) {
  const queryClient = useQueryClient()
  const [name, setName] = useState(agent.name)
  const [persona, setPersona] = useState(agent.persona ?? "")

  const save = useMutation({
    mutationFn: async () =>
      AgentsService.updateAgent({
        path: { agent_id: agent.id },
        body: { name: name.trim(), persona: persona.trim() || null },
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: agentKeys.all })
      toast.success("Saved")
    },
    onError: (error: { body?: { detail?: string } }) =>
      toast.error(error.body?.detail ?? "Could not save"),
  })

  const dirty = name.trim() !== agent.name || persona !== (agent.persona ?? "")

  return (
    <Card>
      <CardHeader>
        <CardTitle>Settings</CardTitle>
        <CardDescription>
          Applies from the agent's next message.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="flex flex-col gap-2">
          <Label htmlFor="name">Name</Label>
          <Input
            id="name"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>
        <div className="flex flex-col gap-2">
          <Label htmlFor="persona">How it should work</Label>
          <Textarea
            id="persona"
            value={persona}
            onChange={(e) => setPersona(e.target.value)}
            rows={4}
            placeholder="Answer in German. Keep it brief. Always tell me where you filed something."
          />
        </div>
        <div>
          <Button
            onClick={() => save.mutate()}
            disabled={!dirty || save.isPending}
          >
            Save changes
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

function DeleteAgentButton({ onConfirm }: { onConfirm: () => void }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <Button variant="outline" onClick={() => setOpen(true)}>
        <Trash2 />
        Delete
      </Button>
      <AlertDialog open={open} onOpenChange={setOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete this agent?</AlertDialogTitle>
            <AlertDialogDescription>
              Its channels disconnect, its conversation history goes, and the
              key it used to reach your knowledge base is revoked. Your pages
              and documents are not affected. This cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={onConfirm}>
              Delete agent
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}
