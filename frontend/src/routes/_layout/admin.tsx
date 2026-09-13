import { useSuspenseQuery } from "@tanstack/react-query"
import { createFileRoute, redirect } from "@tanstack/react-router"
import { Suspense } from "react"
import { z } from "zod"

import { type UserPublic, UsersService } from "@/client"
import AddUser from "@/components/Admin/AddUser"
import { ChannelsPanel } from "@/components/Admin/ChannelsPanel"
import { columns, type UserTableData } from "@/components/Admin/columns"
import { DataSourcesPanel } from "@/components/Admin/DataSourcesPanel"
import { DataTable } from "@/components/Common/DataTable"
import { PageContainer, PageHeader } from "@/components/Layout/PageContainer"
import PendingUsers from "@/components/Pending/PendingUsers"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import useAuth from "@/hooks/useAuth"

function getUsersQueryOptions() {
  return {
    queryFn: async () =>
      (await UsersService.readUsers({ query: { skip: 0, limit: 100 } })).data,
    queryKey: ["users"],
  }
}

const adminSearchSchema = z.object({
  tab: z.enum(["users", "channels", "data-sources"]).catch("users"),
})

export const Route = createFileRoute("/_layout/admin")({
  component: Admin,
  validateSearch: adminSearchSchema,
  beforeLoad: async () => {
    const { data: user } = await UsersService.readUserMe()
    if (!user.is_superuser) {
      throw redirect({
        to: "/",
      })
    }
  },
  head: () => ({
    meta: [
      {
        title: "Admin - PlusGPT",
      },
    ],
  }),
})

function UsersTableContent() {
  const { user: currentUser } = useAuth()
  const { data: users } = useSuspenseQuery(getUsersQueryOptions())

  const tableData: UserTableData[] = users.data.map((user: UserPublic) => ({
    ...user,
    isCurrentUser: currentUser?.id === user.id,
  }))

  return <DataTable columns={columns} data={tableData} />
}

function UsersTable() {
  return (
    <Suspense fallback={<PendingUsers />}>
      <UsersTableContent />
    </Suspense>
  )
}

function Admin() {
  const { tab } = Route.useSearch()
  const navigate = Route.useNavigate()

  return (
    <PageContainer className="flex flex-col gap-6">
      <PageHeader
        title="Administration"
        description="Accounts, and the messaging channels people can reach their agents on."
        actions={tab === "users" ? <AddUser /> : undefined}
      />
      <Tabs
        value={tab}
        onValueChange={(value) =>
          navigate({
            search: { tab: value as "users" | "channels" | "data-sources" },
            replace: true,
          })
        }
      >
        <TabsList className="h-auto flex-wrap">
          <TabsTrigger value="users">Users</TabsTrigger>
          <TabsTrigger value="channels">Channels</TabsTrigger>
          <TabsTrigger value="data-sources">Data sources</TabsTrigger>
        </TabsList>
        <TabsContent value="users" className="pt-4">
          <UsersTable />
        </TabsContent>
        <TabsContent value="channels" className="pt-4">
          <ChannelsPanel />
        </TabsContent>
        <TabsContent value="data-sources" className="pt-4">
          <DataSourcesPanel />
        </TabsContent>
      </Tabs>
    </PageContainer>
  )
}
