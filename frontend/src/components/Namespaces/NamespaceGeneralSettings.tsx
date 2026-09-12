import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"
import { useForm } from "react-hook-form"
import { z } from "zod"

import { type NamespacePublic, NamespacesService } from "@/client"
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form"
import { Input } from "@/components/ui/input"
import { LoadingButton } from "@/components/ui/loading-button"
import { Textarea } from "@/components/ui/textarea"
import useCustomToast from "@/hooks/useCustomToast"
import { queryKeys } from "@/lib/queryKeys"
import { handleError } from "@/utils"
import { IconColorPicker } from "./IconColorPicker"

const schema = z.object({
  name: z.string().trim().min(1, "Name is required").max(60),
  description: z.string().trim().max(500).optional(),
  icon: z.string(),
  color: z.string(),
})
type FormData = z.infer<typeof schema>

export function NamespaceGeneralSettings({
  namespace,
}: {
  namespace: NamespacePublic
}) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const form = useForm<FormData>({
    resolver: zodResolver(schema),
    values: {
      name: namespace.name,
      description: namespace.description ?? "",
      icon: namespace.icon ?? "folder",
      color: namespace.color ?? "indigo",
    },
  })

  const mutation = useMutation({
    mutationFn: async (d: FormData) =>
      (
        await NamespacesService.updateNamespace({
          path: { namespace_id: namespace.id },
          body: {
            name: d.name,
            description: d.description || null,
            icon: d.icon,
            color: d.color,
          },
        })
      ).data,
    onSuccess: (ns) => {
      showSuccessToast("Space updated")
      queryClient.invalidateQueries({ queryKey: queryKeys.namespaces.all })
      if (ns.slug !== namespace.slug) {
        navigate({
          to: "/s/$namespaceSlug/settings",
          params: { namespaceSlug: ns.slug },
          search: { tab: "general" },
          replace: true,
        })
      }
    },
    onError: handleError.bind(showErrorToast),
  })

  return (
    <Form {...form}>
      <form onSubmit={form.handleSubmit((d) => mutation.mutate(d))}>
        <Card>
          <CardHeader>
            <CardTitle>General</CardTitle>
            <CardDescription>
              Name, description and appearance of the space.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-5">
            <FormField
              control={form.control}
              name="name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Name</FormLabel>
                  <FormControl>
                    <Input data-testid="space-settings-name" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="description"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Description</FormLabel>
                  <FormControl>
                    <Textarea rows={3} {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormItem>
              <FormLabel>Icon &amp; colour</FormLabel>
              <IconColorPicker
                icon={form.watch("icon")}
                color={form.watch("color")}
                onIconChange={(v) =>
                  form.setValue("icon", v, { shouldDirty: true })
                }
                onColorChange={(v) =>
                  form.setValue("color", v, { shouldDirty: true })
                }
              />
            </FormItem>
          </CardContent>
          <CardFooter className="justify-end">
            <LoadingButton
              type="submit"
              loading={mutation.isPending}
              disabled={!form.formState.isDirty}
              data-testid="space-settings-save"
            >
              Save changes
            </LoadingButton>
          </CardFooter>
        </Card>
      </form>
    </Form>
  )
}
