import { queryOptions } from "@tanstack/react-query"

import { FoldersService } from "@/client"
import { queryKeys } from "@/lib/queryKeys"

export function folderQuery(folderId: string) {
  return queryOptions({
    queryKey: queryKeys.folders.detail(folderId),
    queryFn: async () =>
      (await FoldersService.readFolder({ path: { folder_id: folderId } })).data,
  })
}
