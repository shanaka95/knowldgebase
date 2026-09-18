import { useQuery } from "@tanstack/react-query"
import { Eye, Send, Users } from "lucide-react"
import { useEffect, useState } from "react"

import { EmailPreview } from "@/components/Marketing/EmailPreview"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
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
  const [confirming, setConfirming] = useState(false)

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

  // Exactly the people ticked on the Contacts tab. There is no second rule,
  // and there was one: a checkbox that widened the audience after the number
  // had been read is the one thing a confirmation screen cannot protect you
  // from. Sending to everybody is what "Select all" over there is for.
  const recipients = selected.size
  const ready = Boolean(from && subject.trim() && body.trim() && recipients > 0)
  // One a second, so the count is also the duration. Worth saying out loud:
  // six hundred addresses is ten minutes of sending, and somebody who expects
  // it to be instant closes the tab and assumes it broke.
  const duration =
    recipients < 60
      ? "under a minute"
      : recipients < 120
        ? "a minute"
        : `${Math.round(recipients / 60)} minutes`

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

        {/* The count, said plainly and before the button rather than beside
            it. This is the one number somebody needs to have read: sending is
            not undoable, and "1" and "617" look identical in a sentence. */}
        <div
          className="flex min-w-0 flex-wrap items-center gap-2 rounded-lg border bg-muted/30 px-3 py-2"
          data-testid="marketing-recipients"
        >
          <Users className="size-4 shrink-0 text-muted-foreground" />
          <span className="min-w-0 text-sm">
            {recipients === 0 ? (
              <>
                Nobody chosen yet. Pick who this goes to on the{" "}
                <strong>Contacts</strong> tab.
              </>
            ) : (
              <>
                This will send{" "}
                <strong className="tabular-nums">{recipients}</strong>{" "}
                {recipients === 1 ? "email" : "emails"}, one a second, so about{" "}
                {duration}.
              </>
            )}
          </span>
        </div>

        <div className="flex min-w-0 flex-wrap items-center justify-end gap-2">
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
            <Button
              disabled={!ready}
              onClick={() => setConfirming(true)}
              data-testid="marketing-send"
            >
              <Send />
              Send
            </Button>
          </div>
        </div>
        {!ready && recipients > 0 && (
          <p className="text-muted-foreground text-xs">
            Fill in a from address, a subject and a message.
          </p>
        )}
      </div>

      <Dialog open={confirming} onOpenChange={setConfirming}>
        <DialogContent
          className="sm:max-w-md"
          data-testid="marketing-confirm-dialog"
        >
          <DialogHeader>
            <DialogTitle>
              Send {recipients} {recipients === 1 ? "email" : "emails"}?
            </DialogTitle>
            <DialogDescription>
              This cannot be undone. Messages already sent stay sent, though you
              can stop the rest at any point.
            </DialogDescription>
          </DialogHeader>
          <dl className="flex min-w-0 flex-col gap-2 text-sm">
            <div className="flex min-w-0 gap-2">
              <dt className="w-20 shrink-0 text-muted-foreground">From</dt>
              <dd className="min-w-0 wrap-anywhere">{from}</dd>
            </div>
            <div className="flex min-w-0 gap-2">
              <dt className="w-20 shrink-0 text-muted-foreground">Subject</dt>
              <dd className="min-w-0 wrap-anywhere">{subject}</dd>
            </div>
            <div className="flex min-w-0 gap-2">
              <dt className="w-20 shrink-0 text-muted-foreground">To</dt>
              <dd className="min-w-0 tabular-nums">
                {recipients} chosen {recipients === 1 ? "address" : "addresses"}
                , over about {duration}
              </dd>
            </div>
          </dl>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirming(false)}>
              Cancel
            </Button>
            <LoadingButton
              loading={create.isPending}
              onClick={() =>
                create.mutate(
                  {
                    from_email: from,
                    subject: subject.trim(),
                    body_html: body,
                    contact_ids: Array.from(selected),
                  },
                  {
                    onSuccess: (campaign) => {
                      setConfirming(false)
                      if (campaign) onSent(campaign.id)
                    },
                  },
                )
              }
              data-testid="marketing-confirm-send"
            >
              Send them
            </LoadingButton>
          </DialogFooter>
        </DialogContent>
      </Dialog>

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
