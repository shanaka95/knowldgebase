import { useQuery } from "@tanstack/react-query"
import { Eye, Send } from "lucide-react"
import { useEffect, useState } from "react"

import { EmailPreview } from "@/components/Marketing/EmailPreview"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { LoadingButton } from "@/components/ui/loading-button"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import {
  marketingSettingsQuery,
  marketingTemplateQuery,
  useCreateCampaign,
  usePreview,
} from "@/queries/adminMarketing"

/**
 * Write it, look at it, send it.
 *
 * The from-address is a list rather than a field because each one has to be a
 * verified SES identity; an address nobody verified fails every message in the
 * campaign, one a second, for as long as the campaign lasts.
 */
export function CampaignComposer({
  selected,
  onSent,
}: {
  selected: Set<string>
  onSent: (campaignId: string) => void
}) {
  const settings = useQuery(marketingSettingsQuery())
  const template = useQuery(marketingTemplateQuery())
  const preview = usePreview()
  const create = useCreateCampaign()

  const [from, setFrom] = useState("")
  const [subject, setSubject] = useState("")
  const [body, setBody] = useState("")
  const [everyone, setEveryone] = useState(false)

  // Seeded once from the server's template. Not a controlled default, or
  // typing would be undone the moment the query refetched.
  useEffect(() => {
    if (template.data && !subject && !body) {
      setSubject(template.data.subject)
      setBody(template.data.body_html)
    }
  }, [template.data, subject, body])

  useEffect(() => {
    if (settings.data && !from) setFrom(settings.data.from_addresses[0] ?? "")
  }, [settings.data, from])

  const recipients = everyone ? (settings.data?.subscribed ?? 0) : selected.size
  const ready = Boolean(from && subject.trim() && body.trim() && recipients > 0)

  return (
    <div className="grid min-w-0 gap-4 lg:grid-cols-2">
      <div className="flex min-w-0 flex-col gap-3">
        <div className="flex min-w-0 flex-col gap-1.5">
          <Label htmlFor="marketing-from">From</Label>
          <Select value={from} onValueChange={setFrom}>
            <SelectTrigger
              id="marketing-from"
              className="w-full"
              data-testid="marketing-from"
            >
              <SelectValue placeholder="Choose an address" />
            </SelectTrigger>
            <SelectContent>
              {(settings.data?.from_addresses ?? []).map((address) => (
                <SelectItem key={address} value={address}>
                  {address}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="flex min-w-0 flex-col gap-1.5">
          <Label htmlFor="marketing-subject">Subject</Label>
          <Input
            id="marketing-subject"
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
            className="min-w-0"
            data-testid="marketing-subject"
          />
        </div>

        <div className="flex min-w-0 flex-col gap-1.5">
          <Label htmlFor="marketing-body">Message</Label>
          <Textarea
            id="marketing-body"
            rows={16}
            value={body}
            onChange={(e) => setBody(e.target.value)}
            className="min-w-0 font-mono text-xs"
            data-testid="marketing-body"
          />
          <p className="text-muted-foreground text-xs">
            HTML. Use <code>{"{{name}}"}</code> for the greeting, which falls
            back to "there" when the list has no usable name, and{" "}
            <code>{"{{email}}"}</code> for the address. The unsubscribe footer
            is added for you.
          </p>
        </div>

        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={everyone}
              onChange={(e) => setEveryone(e.target.checked)}
              data-testid="marketing-everyone"
            />
            Send to everyone still subscribed
          </label>
        </div>

        <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
          <span
            className="text-muted-foreground text-sm"
            data-testid="marketing-recipients"
          >
            {recipients} {recipients === 1 ? "recipient" : "recipients"}
          </span>
          <div className="flex items-center gap-2">
            <LoadingButton
              variant="outline"
              loading={preview.isPending}
              onClick={() =>
                preview.mutate({
                  subject,
                  body_html: body,
                  // Somebody who is actually going to get this, so the greeting
                  // in the preview is the greeting that gets sent. Falls back
                  // to a stand-in only when nobody has been picked yet.
                  contact_id: Array.from(selected)[0] ?? null,
                })
              }
              data-testid="marketing-preview-button"
            >
              <Eye />
              Preview
            </LoadingButton>
            <LoadingButton
              loading={create.isPending}
              disabled={!ready}
              onClick={() =>
                create.mutate(
                  {
                    from_email: from,
                    subject: subject.trim(),
                    body_html: body,
                    contact_ids: everyone ? [] : Array.from(selected),
                    all_subscribed: everyone,
                  },
                  { onSuccess: (campaign) => campaign && onSent(campaign.id) },
                )
              }
              data-testid="marketing-send"
            >
              <Send />
              Send
            </LoadingButton>
          </div>
        </div>
        {!ready && (
          <p className="text-muted-foreground text-xs">
            {recipients === 0
              ? "Choose who this goes to on the Contacts tab, or tick everyone."
              : "Fill in a from address, a subject and a message."}
          </p>
        )}
      </div>

      <div className="min-w-0">
        <EmailPreview
          loading={preview.isPending}
          html={preview.data?.html}
          subject={preview.data?.subject}
          to={preview.data?.to_email}
        />
      </div>
    </div>
  )
}
