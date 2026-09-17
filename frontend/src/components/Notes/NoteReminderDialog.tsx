import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { addDays, format, nextMonday, nextSaturday, setHours } from "date-fns"
import { useState } from "react"
import { toast } from "sonner"

import {
  type NoteReminderUpsert,
  type ReminderEnds,
  type ReminderRecurrence,
  UserNotesService,
} from "@/client"
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
import { userNoteKeys } from "@/queries/userNotes"

/**
 * Native date and time inputs, not a calendar component.
 *
 * `Usage/RangePicker` already argues this in this codebase: a calendar is a
 * second dependency for a control used on two screens, and the native input
 * gives real wheel pickers on iOS and Android, which beat a 7x5 grid of tap
 * targets at 320px. What a month view would buy is bought by the presets.
 */
const RECURRENCE: { value: ReminderRecurrence; label: string }[] = [
  { value: "none", label: "Does not repeat" },
  { value: "daily", label: "Every day" },
  { value: "weekly", label: "Every week" },
  { value: "monthly", label: "Every month" },
  { value: "yearly", label: "Every year" },
]

function toParts(when: Date): { date: string; time: string } {
  return { date: format(when, "yyyy-MM-dd"), time: format(when, "HH:mm") }
}

export function NoteReminderDialog({
  noteId,
  noteTitle,
  open,
  onOpenChange,
}: {
  noteId: string
  noteTitle: string
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const queryClient = useQueryClient()
  const existing = useQuery({
    queryKey: [...userNoteKeys.detail(noteId), "reminder"],
    queryFn: async () =>
      (await UserNotesService.notesReadReminder({ path: { note_id: noteId } }))
        .data,
    enabled: open,
  })

  const [date, setDate] = useState(toParts(addDays(new Date(), 1)).date)
  const [time, setTime] = useState("09:00")
  const [recurrence, setRecurrence] = useState<ReminderRecurrence>("none")
  const [ends, setEnds] = useState<ReminderEnds>("never")
  const [endsOn, setEndsOn] = useState("")
  const [endsAfter, setEndsAfter] = useState("10")

  // Snapshotted and sent with the reminder. Without the zone name a recurring
  // reminder drifts by an hour at the next daylight-saving change.
  const zone = Intl.DateTimeFormat().resolvedOptions().timeZone

  const applyPreset = (when: Date) => {
    const parts = toParts(when)
    setDate(parts.date)
    setTime(parts.time)
  }

  const save = useMutation({
    mutationFn: async () => {
      const body: NoteReminderUpsert = {
        // A naive local wall clock: the server is told which zone separately,
        // because an instant is ambiguous about which reading was meant.
        at: `${date}T${time}:00`,
        timezone: zone,
        recurrence,
        ends: recurrence === "none" ? "never" : ends,
        ends_on: ends === "on_date" && endsOn ? endsOn : null,
        ends_after: ends === "after" ? Number(endsAfter) || 1 : null,
      }
      return (
        await UserNotesService.notesSetReminder({
          path: { note_id: noteId },
          body,
        })
      ).data
    },
    onSuccess: () => {
      toast.success("Reminder set")
      void queryClient.invalidateQueries({ queryKey: userNoteKeys.all })
      onOpenChange(false)
    },
    onError: (error: Error) =>
      toast.error(error.message || "The reminder could not be set"),
  })

  const remove = useMutation({
    mutationFn: async () =>
      (
        await UserNotesService.notesCancelReminder({
          path: { note_id: noteId },
        })
      ).data,
    onSuccess: () => {
      toast.success("Reminder removed")
      void queryClient.invalidateQueries({ queryKey: userNoteKeys.all })
      onOpenChange(false)
    },
  })

  // The control that actually prevents mistakes: the whole rule, in a sentence.
  const sentence = (() => {
    const at = time
    const when = new Date(`${date}T${time}:00`)
    const on = Number.isNaN(when.getTime()) ? date : format(when, "d MMMM yyyy")
    if (recurrence === "none") return `Emailed once, at ${at} on ${on}.`
    const every = {
      daily: "every day",
      weekly: `every ${format(when, "EEEE")}`,
      monthly: `on the ${format(when, "do")} of each month`,
      yearly: `every ${format(when, "d MMMM")}`,
      none: "",
    }[recurrence]
    let tail = "."
    if (ends === "on_date" && endsOn) tail = `, until ${endsOn}.`
    if (ends === "after") tail = `, ${endsAfter} times in all.`
    return `Emailed ${every} at ${at}${tail}`
  })()

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="sm:max-w-md"
        data-testid="notes-reminder-dialog"
      >
        <DialogHeader>
          <DialogTitle>Remind me about this</DialogTitle>
          <DialogDescription>
            An email with “{noteTitle || "Untitled"}”, sent to you.
          </DialogDescription>
        </DialogHeader>

        <div className="flex min-w-0 flex-col gap-4">
          <div className="flex min-w-0 flex-wrap gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => applyPreset(setHours(addDays(new Date(), 1), 9))}
              data-testid="notes-reminder-preset-tomorrow"
            >
              Tomorrow 9:00
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => applyPreset(setHours(nextSaturday(new Date()), 9))}
              data-testid="notes-reminder-preset-weekend"
            >
              This weekend
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => applyPreset(setHours(nextMonday(new Date()), 9))}
              data-testid="notes-reminder-preset-nextweek"
            >
              Next week
            </Button>
          </div>

          {/* Shrinks rather than pushing the dialog sideways: two fixed fields
              plus their labels do not fit a 320px phone on one row. */}
          <div className="flex w-full min-w-0 items-end gap-2">
            <div className="flex min-w-0 flex-1 flex-col gap-1.5">
              <Label htmlFor="notes-reminder-date">Date</Label>
              <Input
                id="notes-reminder-date"
                type="date"
                value={date}
                min={format(new Date(), "yyyy-MM-dd")}
                onChange={(e) => setDate(e.target.value)}
                className="min-w-0"
                data-testid="notes-reminder-date"
              />
            </div>
            <div className="flex min-w-0 flex-1 flex-col gap-1.5">
              <Label htmlFor="notes-reminder-time">Time</Label>
              <Input
                id="notes-reminder-time"
                type="time"
                value={time}
                onChange={(e) => setTime(e.target.value)}
                className="min-w-0"
                data-testid="notes-reminder-time"
              />
            </div>
          </div>

          <div className="flex min-w-0 flex-col gap-1.5">
            <Label htmlFor="notes-reminder-repeat">Repeats</Label>
            <Select
              value={recurrence}
              onValueChange={(v) => setRecurrence(v as ReminderRecurrence)}
            >
              <SelectTrigger
                id="notes-reminder-repeat"
                className="w-full"
                data-testid="notes-reminder-repeat"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {RECURRENCE.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {recurrence !== "none" && (
            <div className="flex min-w-0 flex-col gap-1.5">
              <Label htmlFor="notes-reminder-end">Ends</Label>
              <Select
                value={ends}
                onValueChange={(v) => setEnds(v as ReminderEnds)}
              >
                <SelectTrigger
                  id="notes-reminder-end"
                  className="w-full"
                  data-testid="notes-reminder-end"
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="never">Never</SelectItem>
                  <SelectItem value="on_date">On a date</SelectItem>
                  <SelectItem value="after">After a number of times</SelectItem>
                </SelectContent>
              </Select>
              {ends === "on_date" && (
                <Input
                  type="date"
                  value={endsOn}
                  min={date}
                  onChange={(e) => setEndsOn(e.target.value)}
                  aria-label="Ends on"
                  data-testid="notes-reminder-end-date"
                />
              )}
              {ends === "after" && (
                <Input
                  type="number"
                  min={1}
                  max={365}
                  value={endsAfter}
                  onChange={(e) => setEndsAfter(e.target.value)}
                  aria-label="Number of times"
                  data-testid="notes-reminder-end-count"
                />
              )}
            </div>
          )}

          <p
            className="wrap-anywhere text-muted-foreground text-sm"
            data-testid="notes-reminder-summary"
          >
            {sentence} Times are in {zone}.
          </p>
        </div>

        <DialogFooter>
          {existing.data && (
            <Button
              variant="ghost"
              onClick={() => remove.mutate()}
              className="text-destructive"
              data-testid="notes-reminder-remove"
            >
              Remove reminder
            </Button>
          )}
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <LoadingButton
            loading={save.isPending}
            onClick={() => save.mutate()}
            data-testid="notes-reminder-save"
          >
            Save
          </LoadingButton>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
