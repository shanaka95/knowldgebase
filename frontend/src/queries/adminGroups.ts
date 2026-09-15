import {
  queryOptions,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query"
import { toast } from "sonner"

import {
  AdminUserGroupsService,
  type AdminUsersPublic,
  AdminUsersService,
  type LimitDefinitionsPublic,
  type UserAssignment,
  type UserGroupCreate,
  type UserGroupsPublic,
  type UserGroupUpdate,
} from "@/client"
import { queryKeys } from "@/lib/queryKeys"

/** Groups, with how many accounts are in each and what they would get. */
export function userGroupsQuery() {
  return queryOptions({
    queryKey: queryKeys.admin.groups(),
    queryFn: async (): Promise<UserGroupsPublic> =>
      (await AdminUserGroupsService.readUserGroups()).data,
  })
}

/**
 * What can be set, described well enough to draw a form from.
 *
 * The forms below are generated from this rather than hard-coding field names,
 * so a limit added to the backend registry appears in the interface without the
 * interface being changed.
 */
export function limitDefinitionsQuery() {
  return queryOptions({
    queryKey: queryKeys.admin.limits(),
    queryFn: async (): Promise<LimitDefinitionsPublic> =>
      (await AdminUserGroupsService.readLimitDefinitions()).data,
    staleTime: 5 * 60_000,
  })
}

/** Accounts with their group and their effective limits — admin only. */
export function adminUsersQuery(params: { q?: string; groupId?: string } = {}) {
  return queryOptions({
    queryKey: queryKeys.admin.users(params),
    queryFn: async (): Promise<AdminUsersPublic> =>
      (
        await AdminUsersService.readAdminUsers({
          query: { limit: 1000, q: params.q, group_id: params.groupId },
        })
      ).data,
  })
}

function useGroupMutation<TVariables>(
  run: (variables: TVariables) => Promise<unknown>,
  { success, failure }: { success: string; failure: string },
) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: run,
    onSuccess: () => toast.success(success),
    onError: (error: { body?: { detail?: string } }) =>
      toast.error(error.body?.detail ?? failure),
    // Groups and users move together: putting somebody in a group changes a
    // member count on one screen and a limit on the other.
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.admin.all })
      void queryClient.invalidateQueries({ queryKey: ["users"] })
    },
  })
}

export function useCreateUserGroup() {
  return useGroupMutation<UserGroupCreate>(
    (body) => AdminUserGroupsService.createUserGroup({ body }),
    { success: "Group created", failure: "The group could not be created" },
  )
}

export function useUpdateUserGroup() {
  return useGroupMutation<{ id: string; body: UserGroupUpdate }>(
    ({ id, body }) =>
      AdminUserGroupsService.updateUserGroup({ path: { group_id: id }, body }),
    { success: "Group saved", failure: "The group could not be saved" },
  )
}

export function useDeleteUserGroup() {
  return useGroupMutation<string>(
    (id) => AdminUserGroupsService.deleteUserGroup({ path: { group_id: id } }),
    { success: "Group deleted", failure: "The group could not be deleted" },
  )
}

export function useAddGroupMembers() {
  return useGroupMutation<{ id: string; userIds: string[] }>(
    ({ id, userIds }) =>
      AdminUserGroupsService.addGroupMembers({
        path: { group_id: id },
        body: { user_ids: userIds },
      }),
    { success: "Members added", failure: "They could not be added" },
  )
}

export function useSetUserAssignment() {
  return useGroupMutation<{ userId: string; body: UserAssignment }>(
    ({ userId, body }) =>
      AdminUsersService.setUserAssignment({ path: { user_id: userId }, body }),
    { success: "Saved", failure: "It could not be saved" },
  )
}
