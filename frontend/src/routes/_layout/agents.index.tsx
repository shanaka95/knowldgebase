import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { Bot, MessageSquare, Plus } from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"

import { AgentsService } from "@/client"
import { ChannelIcon } from "@/components/Common/ChannelIcon"
import { PageContainer, PageHeader } from "@/components/Layout/PageContainer"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Skeleton } from "@/components/ui/skeleton"
import { Textarea } from "@/components/ui/textarea"
import { agentKeys, agentsQuery, channelLabel } from "@/queries/agents"

export const Route = createFileRoute("/_layout/agents/")({
  component: AgentsPage,
  staticData: { crumb: "Agents" },
  loader: ({ context: { queryClient } }) => {
    void queryClient.prefetchQuery(agentsQuery())
  },
  head: () => ({ meta: [{ title: "Agents - PlusGPT" }] }),
})

function AgentsPage() {
  const { data, isPending } = useQuery(agentsQuery())
  const [creating, setCreating] = useState(false)

  return (
    <PageContainer className="flex flex-col gap-6">
      <PageHeader
        title="Agents"
        description="An assistant you can message from WhatsApp or Telegram. It answers from your knowledge base and can save notes as pages."
        actions={
          <Button onClick={() => setCreating(true)} data-testid="agent-new">
            <Plus />
            New agent
          </Button>
        }
      />

      {isPending || !data ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Skeleton className="h-28 w-full" />
          <Skeleton className="h-28 w-full" />
        </div>
      ) : data.data.length === 0 ? (
        <Empty>
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <Bot />
            </EmptyMedia>
            <EmptyTitle>No agents yet</EmptyTitle>
            <EmptyDescription>
              An agent puts a chat window in front of your knowledge base.
              Create one, connect a messaging channel, and you can ask it
              questions or dictate a note without opening PlusGPT.
            </EmptyDescription>
          </EmptyHeader>
          <EmptyContent>
            <Button onClick={() => setCreating(true)}>
              <Plus />
              Create an agent
            </Button>
          </EmptyContent>
        </Empty>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {data.data.map((agent) => (
            <Link
              key={agent.id}
              to="/agents/$agentId"
              params={{ agentId: agent.id }}
              className="block"
            >
              <Card className="h-full transition-colors hover:border-primary/50">
                <CardContent className="flex items-start gap-3">
                  <div className="rounded-md bg-muted p-2">
                    <Bot className="size-5" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <p className="truncate font-medium">{agent.name}</p>
                      {agent.status !== "ready" && (
                        <Badge variant="secondary">{agent.status}</Badge>
                      )}
                    </div>
                    {agent.connections.length === 0 ? (
                      <p className="mt-1 flex items-center gap-1.5 text-sm text-muted-foreground">
                        <MessageSquare className="size-3.5 shrink-0" />
                        No channels connected
                      </p>
                    ) : (
                      // The marks alone: at a glance the reader is looking for
                      // which platforms, and the logos answer that faster than
                      // the words do.
                      <p className="mt-1.5 flex items-center gap-1.5">
                        {agent.connections.map((c) => (
                          <ChannelIcon
                            key={c.id}
                            channel={c.channel_type}
                            className="size-4"
                          />
                        ))}
                        <span className="sr-only">
                          {agent.connections
                            .map((c) => channelLabel(c.channel_type))
                            .join(", ")}
                        </span>
                      </p>
                    )}
                  </div>
                </CardContent>
              </Card>
            </Link>
          ))}
        </div>
      )}

      <CreateAgentDialog open={creating} onOpenChange={setCreating} />
    </PageContainer>
  )
}

function CreateAgentDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const queryClient = useQueryClient()
  const [name, setName] = useState("")
  const [persona, setPersona] = useState("")

  const create = useMutation({
    mutationFn: async () =>
      (
        await AgentsService.createAgent({
          body: { name: name.trim(), persona: persona.trim() || null },
        })
      ).data,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: agentKeys.all })
      toast.success("Agent created")
      onOpenChange(false)
      setName("")
      setPersona("")
    },
    onError: (error: { body?: { detail?: string } }) =>
      toast.error(error.body?.detail ?? "The agent could not be created"),
  })

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New agent</DialogTitle>
          <DialogDescription>
            It reads your knowledge base and can write pages from what you tell
            it. Connect a channel next, and you can talk to it from there.
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-2">
            <Label htmlFor="agent-name">Name</Label>
            <Input
              id="agent-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Sam"
              autoFocus
            />
            <p className="text-xs text-muted-foreground">
              What it calls itself when it answers you.
            </p>
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="agent-persona">How it should work (optional)</Label>
            <Textarea
              id="agent-persona"
              value={persona}
              onChange={(e) => setPersona(e.target.value)}
              placeholder="Answer in German. Keep it brief. Always tell me where you filed something."
              rows={3}
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            onClick={() => create.mutate()}
            disabled={!name.trim() || create.isPending}
          >
            Create agent
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
