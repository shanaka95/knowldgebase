import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"
import { useForm } from "react-hook-form"
import { z } from "zod"

import { type NamespacePublic, NamespacesService } from "@/client"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
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
import { rememberNamespaceSlug } from "@/hooks/useNamespaces"
import { queryKeys } from "@/lib/queryKeys"
import { handleError } from "@/utils"
import { IconColorPicker } from "./IconColorPicker"

const schema = z.object({
  name: z
    .string()
    .trim()
    .min(1, "Name is required")
    .max(60, "Max 60 characters"),
  description: z.string().trim().max(500, "Max 500 characters").optional(),
  icon: z.string(),
  color: z.string(),
})
type FormData = z.infer<typeof schema>

interface NamespaceFormDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  namespace?: NamespacePublic | null
  onSaved?: (ns: NamespacePublic) => void
}

/** Create (no `namespace`) or edit a space. */
export function NamespaceFormDialog({
  open,
  onOpenChange,
  namespace,
  onSaved,
}: NamespaceFormDialogProps) {
  const isEdit = Boolean(namespace)
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const { showSuccessToast, showErrorToast } = useCustomToast()

  const form = useForm<FormData>({
    resolver: zodResolver(schema),
    mode: "onBlur",
    defaultValues: {
      name: namespace?.name ?? "",
      description: namespace?.description ?? "",
      icon: namespace?.icon ?? "folder",
      color: namespace?.color ?? "indigo",
    },
  })

  const mutation = useMutation({
    mutationFn: async (data: FormData) => {
      const body = {
        name: data.name,
        description: data.description || null,
        icon: data.icon,
        color: data.color,
      }
      if (namespace) {
        return (
          await NamespacesService.updateNamespace({
            path: { namespace_id: namespace.id },
            body,
          })
        ).data
      }
      return (await NamespacesService.createNamespace({ body })).data
    },
    onSuccess: (ns) => {
      showSuccessToast(isEdit ? "Space updated" : "Space created")
      queryClient.invalidateQueries({ queryKey: queryKeys.namespaces.all })
      onOpenChange(false)
      onSaved?.(ns)
      if (!isEdit) {
        rememberNamespaceSlug(ns.slug)
        navigate({
          to: "/s/$namespaceSlug",
          params: { namespaceSlug: ns.slug },
        })
      } else if (namespace && namespace.slug !== ns.slug) {
        navigate({
          to: "/s/$namespaceSlug",
          params: { namespaceSlug: ns.slug },
        })
      }
    },
    onError: handleError.bind(showErrorToast),
  })

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg" data-testid="namespace-dialog">
        <DialogHeader>
          <DialogTitle>{isEdit ? "Edit space" : "Create a space"}</DialogTitle>
          <DialogDescription>
            {isEdit
              ? "Change the name, description or look of this space."
              : "Spaces group related pages, like Personal, Office or a project."}
          </DialogDescription>
        </DialogHeader>
        <Form {...form}>
          <form
            onSubmit={form.handleSubmit((d) => mutation.mutate(d))}
            className="flex flex-col gap-5"
          >
            <FormField
              control={form.control}
              name="name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>
                    Name <span className="text-destructive">*</span>
                  </FormLabel>
                  <FormControl>
                    <Input
                      placeholder="e.g. Office"
                      autoFocus
                      data-testid="namespace-name"
                      {...field}
                    />
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
                    <Textarea
                      rows={2}
                      placeholder="What lives in this space?"
                      {...field}
                    />
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
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => onOpenChange(false)}
                disabled={mutation.isPending}
              >
                Cancel
              </Button>
              <LoadingButton
                type="submit"
                loading={mutation.isPending}
                data-testid="namespace-submit"
              >
                {isEdit ? "Save changes" : "Create space"}
              </LoadingButton>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  )
}
