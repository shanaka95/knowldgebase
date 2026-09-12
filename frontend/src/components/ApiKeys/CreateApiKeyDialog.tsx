import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Check, Copy, KeyRound, Plus, ShieldAlert } from "lucide-react"
import { useState } from "react"
import { useForm } from "react-hook-form"
import { z } from "zod"

import { type ApiKeyCreated, type ApiKeyScope, ApiKeysService } from "@/client"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form"
import { Input } from "@/components/ui/input"
import { LoadingButton } from "@/components/ui/loading-button"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { useCopyToClipboard } from "@/hooks/useCopyToClipboard"
import useCustomToast from "@/hooks/useCustomToast"
import { queryKeys } from "@/lib/queryKeys"
import { cn } from "@/lib/utils"
import { handleError } from "@/utils"

const schema = z.object({
  name: z.string().trim().min(1, "Give the key a name").max(100),
  scope: z.enum(["read", "write"]),
  expires: z.enum(["never", "30", "90", "365"]),
})
type FormData = z.infer<typeof schema>

const SCOPES: { value: ApiKeyScope; label: string; hint: string }[] = [
  {
    value: "read",
    label: "Read",
    hint: "List and read spaces, folders, pages and attachments.",
  },
  {
    value: "write",
    label: "Read & write",
    hint: "Everything in read, plus create, update, move, share and delete.",
  },
]

export function CreateApiKeyDialog() {
  const [open, setOpen] = useState(false)
  const [created, setCreated] = useState<ApiKeyCreated | null>(null)
  const [copied, copy] = useCopyToClipboard()
  const queryClient = useQueryClient()
  const { showErrorToast } = useCustomToast()

  const form = useForm<FormData>({
    resolver: zodResolver(schema),
    defaultValues: { name: "", scope: "read", expires: "never" },
  })

  const mutation = useMutation({
    mutationFn: async (d: FormData) =>
      (
        await ApiKeysService.createApiKey({
          body: {
            name: d.name,
            scope: d.scope,
            expires_in_days: d.expires === "never" ? null : Number(d.expires),
          },
        })
      ).data,
    onSuccess: (key) => {
      setCreated(key)
      queryClient.invalidateQueries({ queryKey: queryKeys.apiKeys })
    },
    onError: handleError.bind(showErrorToast),
  })

  const close = () => {
    setOpen(false)
    setCreated(null)
    form.reset()
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        // once a key is shown, only the explicit button closes the dialog
        if (!o && created) return
        if (!o) close()
        else setOpen(true)
      }}
    >
      <DialogTrigger asChild>
        <Button data-testid="create-api-key">
          <Plus />
          Create API key
        </Button>
      </DialogTrigger>
      <DialogContent
        className="sm:max-w-lg"
        data-testid="create-api-key-dialog"
      >
        {created ? (
          <>
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2">
                <KeyRound className="size-5 text-primary" />
                Your new API key
              </DialogTitle>
              <DialogDescription>
                Use it as{" "}
                <code className="font-mono">Authorization: Bearer …</code> when
                calling the API.
              </DialogDescription>
            </DialogHeader>
            <div className="flex flex-col gap-3">
              <div className="flex gap-2">
                <Input
                  readOnly
                  value={created.key}
                  className="font-mono text-xs"
                  onFocus={(e) => e.target.select()}
                  data-testid="api-key-value"
                />
                <Button
                  variant="outline"
                  onClick={() => copy(created.key)}
                  className={cn(copied && "border-success text-success")}
                  data-testid="api-key-copy"
                >
                  {copied ? <Check /> : <Copy />}
                  {copied ? "Copied" : "Copy"}
                </Button>
              </div>
              <Alert className="border-warning/50 bg-warning/10">
                <ShieldAlert className="text-warning-foreground dark:text-warning" />
                <AlertTitle>You won't see this key again</AlertTitle>
                <AlertDescription>
                  Store it somewhere safe now. If you lose it, revoke it and
                  create a new one.
                </AlertDescription>
              </Alert>
            </div>
            <DialogFooter>
              <Button onClick={close} data-testid="api-key-done">
                I've copied it
              </Button>
            </DialogFooter>
          </>
        ) : (
          <>
            <DialogHeader>
              <DialogTitle>Create API key</DialogTitle>
              <DialogDescription>
                Personal keys let scripts and third-party apps use the API on
                your behalf.
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
                      <FormLabel>Name</FormLabel>
                      <FormControl>
                        <Input
                          placeholder="e.g. Zapier integration"
                          autoFocus
                          data-testid="api-key-name"
                          {...field}
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <FormField
                  control={form.control}
                  name="scope"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Permissions</FormLabel>
                      <div className="grid gap-2 sm:grid-cols-2">
                        {SCOPES.map((s) => {
                          const selected = field.value === s.value
                          return (
                            <button
                              key={s.value}
                              type="button"
                              aria-pressed={selected}
                              onClick={() => field.onChange(s.value)}
                              data-testid={`api-key-scope-${s.value}`}
                              className={cn(
                                "flex flex-col items-start gap-1 rounded-md border p-3 text-left text-sm transition hover:bg-accent",
                                selected &&
                                  "border-primary bg-primary/5 ring-1 ring-primary",
                              )}
                            >
                              <span className="font-medium">{s.label}</span>
                              <span className="text-xs text-muted-foreground">
                                {s.hint}
                              </span>
                            </button>
                          )
                        })}
                      </div>
                    </FormItem>
                  )}
                />
                <FormField
                  control={form.control}
                  name="expires"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Expiry</FormLabel>
                      <Select
                        value={field.value}
                        onValueChange={field.onChange}
                      >
                        <FormControl>
                          <SelectTrigger
                            className="w-full"
                            data-testid="api-key-expiry"
                          >
                            <SelectValue />
                          </SelectTrigger>
                        </FormControl>
                        <SelectContent>
                          <SelectItem value="never">Never expires</SelectItem>
                          <SelectItem value="30">30 days</SelectItem>
                          <SelectItem value="90">90 days</SelectItem>
                          <SelectItem value="365">1 year</SelectItem>
                        </SelectContent>
                      </Select>
                      <FormDescription>
                        You can revoke a key at any time.
                      </FormDescription>
                    </FormItem>
                  )}
                />
                <DialogFooter>
                  <Button
                    type="button"
                    variant="outline"
                    onClick={close}
                    disabled={mutation.isPending}
                  >
                    Cancel
                  </Button>
                  <LoadingButton
                    type="submit"
                    loading={mutation.isPending}
                    data-testid="api-key-submit"
                  >
                    Create key
                  </LoadingButton>
                </DialogFooter>
              </form>
            </Form>
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}
