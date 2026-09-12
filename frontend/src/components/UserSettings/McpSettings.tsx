import { useQuery } from "@tanstack/react-query"
import {
  Check,
  Copy,
  FilePlus2,
  FileText,
  FolderPlus,
  MessageCircleQuestion,
  Plug,
  Search,
  Upload,
} from "lucide-react"

import type { ApiKeyCreated, ApiKeyPublic } from "@/client"
import { ApiKeyList } from "@/components/ApiKeys/ApiKeysTable"
import { CreateApiKeyDialog } from "@/components/ApiKeys/CreateApiKeyDialog"
import { APP_NAME } from "@/components/Common/Logo"
import { EmptyState } from "@/components/Layout/EmptyState"
import { PendingList } from "@/components/Pending/PendingList"
import { Button } from "@/components/ui/button"
import { useCopyToClipboard } from "@/hooks/useCopyToClipboard"
import { cn } from "@/lib/utils"
import { apiKeysQuery } from "@/queries/apiKeys"

/**
 * MCP connections are ordinary API keys; the prefix is what tells them apart
 * from keys made for scripts, both here and in the API keys tab.
 */
const MCP_NAME_PREFIX = "MCP · "

function isMcpKey(key: ApiKeyPublic) {
  return key.name.startsWith(MCP_NAME_PREFIX)
}

/** The endpoint is wherever this app is served from, so it is right anywhere. */
function mcpUrl() {
  return `${window.location.origin}/mcp`
}

function mcpConfig(key: string) {
  return JSON.stringify(
    {
      mcpServers: {
        plusgpt: {
          type: "http",
          url: mcpUrl(),
          headers: { Authorization: `Bearer ${key}` },
        },
      },
    },
    null,
    2,
  )
}

const ABILITIES = [
  { icon: Search, text: "Search your pages" },
  { icon: MessageCircleQuestion, text: "Answer questions from them" },
  { icon: FileText, text: "Read a page in full" },
  { icon: FilePlus2, text: "Create and update pages" },
  { icon: FolderPlus, text: "Create folders" },
  { icon: Upload, text: "Upload PDFs and images" },
]

function ConfigBlock({ created }: { created: ApiKeyCreated }) {
  const [copied, copy] = useCopyToClipboard()
  const config = mcpConfig(created.key)
  return (
    <div className="flex flex-col gap-1.5">
      <p className="text-sm font-medium">Add this to your assistant's config</p>
      <div className="relative">
        <pre
          className="overflow-x-auto rounded-md border bg-muted p-3 text-xs leading-relaxed font-mono"
          data-testid="mcp-config"
        >
          {config}
        </pre>
        <Button
          size="sm"
          variant="outline"
          className={cn("absolute top-2 right-2", copied && "border-success")}
          onClick={() => copy(config)}
          data-testid="mcp-config-copy"
        >
          {copied ? <Check /> : <Copy />}
          {copied ? "Copied" : "Copy"}
        </Button>
      </div>
    </div>
  )
}

export function McpSettings() {
  const { data, isPending } = useQuery(apiKeysQuery())
  const connections = (data?.data ?? []).filter(
    (k) => !k.revoked_at && isMcpKey(k),
  )

  return (
    <div className="flex max-w-4xl flex-col gap-6" data-testid="mcp-settings">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="max-w-2xl">
          <h2 className="text-lg font-semibold">MCP</h2>
          <p className="text-sm text-muted-foreground">
            The Model Context Protocol lets an AI assistant — Claude, for
            instance — read and write this knowledge base while you chat with
            it. A connection reaches only the spaces and pages of the account
            whose key it holds, and nothing else in {APP_NAME}.
          </p>
        </div>
        <CreateApiKeyDialog
          trigger={
            <Button data-testid="create-mcp-connection">
              <Plug />
              Create an MCP connection
            </Button>
          }
          title="Create an MCP connection"
          description="This creates a read & write API key for your assistant, then shows the config to paste into it."
          nameLabel="Connection name"
          namePlaceholder="e.g. Claude Desktop"
          namePrefix={MCP_NAME_PREFIX}
          scope="write"
          submitLabel="Create connection"
          renderCreated={(created) => <ConfigBlock created={created} />}
        />
      </div>

      <div className="flex flex-col gap-2">
        <p className="text-sm font-medium">What the assistant can do</p>
        <ul className="grid gap-2 text-sm text-muted-foreground sm:grid-cols-2">
          {ABILITIES.map((ability) => (
            <li key={ability.text} className="flex items-center gap-2">
              <ability.icon className="size-4 shrink-0" />
              {ability.text}
            </li>
          ))}
        </ul>
        <p className="text-sm text-muted-foreground">
          Endpoint: <code className="font-mono text-xs">{mcpUrl()}</code>
        </p>
      </div>

      <div className="flex flex-col gap-3">
        <p className="text-sm font-medium">Your connections</p>
        {isPending ? (
          <PendingList rows={2} />
        ) : connections.length === 0 ? (
          <EmptyState
            compact
            icon={Plug}
            title="No MCP connections yet"
            description="Create one to let an assistant work with your pages. You can revoke it at any time."
          />
        ) : (
          <ApiKeyList keys={connections} rowTestId="mcp-connection-row" />
        )}
      </div>
    </div>
  )
}

export default McpSettings
