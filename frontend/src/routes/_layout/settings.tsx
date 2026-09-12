import { createFileRoute, useNavigate } from "@tanstack/react-router"
import { z } from "zod"
import ApiKeysTable from "@/components/ApiKeys/ApiKeysTable"
import { PageContainer, PageHeader } from "@/components/Layout/PageContainer"
import AppearanceSettings from "@/components/UserSettings/AppearanceSettings"
import DeleteAccount from "@/components/UserSettings/DeleteAccount"
import Developer from "@/components/UserSettings/Developer"
import McpSettings from "@/components/UserSettings/McpSettings"
import SecuritySettings from "@/components/UserSettings/SecuritySettings"
import UserInformation from "@/components/UserSettings/UserInformation"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import useAuth from "@/hooks/useAuth"

const TAB_VALUES = [
  "profile",
  "password",
  "appearance",
  "api-keys",
  "mcp",
  "developer",
  "danger",
] as const
type TabValue = (typeof TAB_VALUES)[number]

const tabsConfig: { value: TabValue; title: string; component: React.FC }[] = [
  { value: "profile", title: "My profile", component: UserInformation },
  { value: "password", title: "Password", component: SecuritySettings },
  { value: "appearance", title: "Appearance", component: AppearanceSettings },
  { value: "api-keys", title: "API keys", component: ApiKeysTable },
  { value: "mcp", title: "MCP", component: McpSettings },
  { value: "developer", title: "Developer", component: Developer },
  { value: "danger", title: "Danger zone", component: DeleteAccount },
]

export const Route = createFileRoute("/_layout/settings")({
  component: UserSettings,
  staticData: { crumb: "Settings" },
  validateSearch: z.object({
    tab: z.enum(TAB_VALUES).catch("profile"),
  }),
  head: () => ({
    meta: [
      {
        title: "Settings - PlusGPT",
      },
    ],
  }),
})

function UserSettings() {
  const { user: currentUser } = useAuth()
  const { tab } = Route.useSearch()
  const navigate = useNavigate({ from: Route.fullPath })

  // superusers cannot delete their own account
  const finalTabs = currentUser?.is_superuser
    ? tabsConfig.filter((t) => t.value !== "danger")
    : tabsConfig

  if (!currentUser) {
    return null
  }

  return (
    <PageContainer className="flex flex-col gap-6">
      <PageHeader
        title="Settings"
        description="Manage your account, appearance and API access."
      />

      <Tabs
        value={tab}
        onValueChange={(value) =>
          navigate({ search: { tab: value as TabValue }, replace: true })
        }
      >
        <TabsList className="h-auto flex-wrap">
          {finalTabs.map((t) => (
            <TabsTrigger key={t.value} value={t.value}>
              {t.title}
            </TabsTrigger>
          ))}
        </TabsList>
        {finalTabs.map((t) => (
          <TabsContent key={t.value} value={t.value} className="pt-4">
            <t.component />
          </TabsContent>
        ))}
      </Tabs>
    </PageContainer>
  )
}
