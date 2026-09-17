import { Loader2, Mic, Square, X } from "lucide-react"
import { useCallback, useState } from "react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import {
  type Recording,
  recorderSupported,
  useNoteRecorder,
} from "@/hooks/useNoteRecorder"
import { cn } from "@/lib/utils"
import { useTranscribe, useVoiceSettings } from "@/queries/voice"

function clock(seconds: number): string {
  const minutes = Math.floor(seconds / 60)
  return `${minutes}:${String(seconds % 60).padStart(2, "0")}`
}

/**
 * Talk instead of typing.
 *
 * Deliberately not a dialog. Dictation is a way of filling in the field you are
 * already looking at, and a modal over it would hide the thing being written
 * and take the focus away from it. The button becomes the recorder in place:
 * one control, three states, and the countdown and level meter beside it.
 *
 * The transcript is handed back rather than saved. Where the words go is the
 * caller's business - a note body, a checklist line, a search box.
 */
export function DictateButton({
  onText,
  label = "Dictate",
  className,
  size = "icon-sm",
}: {
  onText: (text: string) => void
  label?: string
  className?: string
  size?: "icon-sm" | "sm"
}) {
  const voice = useVoiceSettings()
  const transcribe = useTranscribe()
  const [lastCost, setLastCost] = useState<number | null>(null)

  const send = useCallback(
    (recording: Recording) => {
      transcribe.mutate(
        {
          blob: recording.blob,
          seconds: recording.seconds,
          mimeType: recording.mimeType,
        },
        {
          onSuccess: (result) => {
            if (!result) return
            if (!result.text) {
              toast.info("Nothing was said in that recording")
              return
            }
            setLastCost(result.credits)
            onText(result.text)
          },
          onError: (error: Error) =>
            toast.error(error.message || "That recording could not be read"),
        },
      )
    },
    [onText, transcribe],
  )

  const maxSeconds = voice.data?.max_seconds ?? 120
  const recorder = useNoteRecorder({
    maxSeconds,
    onFinished: send,
    onError: (message) => toast.error(message),
  })

  // A deployment with no model configured does not offer a microphone at all,
  // and neither does a browser that cannot record one.
  if (!voice.data?.enabled || !recorderSupported()) return null

  if (transcribe.isPending) {
    return (
      <Button
        variant="ghost"
        size={size}
        disabled
        className={className}
        aria-label="Writing down what you said"
        data-testid="notes-dictate-working"
      >
        <Loader2 className="animate-spin" />
        {size === "sm" && "Writing it down…"}
      </Button>
    )
  }

  if (recorder.recording || recorder.state === "stopping") {
    return (
      <div
        className={cn("flex min-w-0 items-center gap-1.5", className)}
        data-testid="notes-dictate-recording"
      >
        {/* Not a waveform: one bar that says the microphone can hear you, which
            is what somebody with a muted headset needs to find out early. */}
        <span
          aria-hidden
          className="h-2 w-2 shrink-0 rounded-full bg-destructive transition-transform"
          style={{
            transform: `scale(${1 + Math.min(recorder.level, 1) * 1.6})`,
          }}
        />
        <span
          className="shrink-0 font-mono text-muted-foreground text-xs tabular-nums"
          data-testid="notes-dictate-clock"
        >
          {clock(recorder.seconds)} / {clock(maxSeconds)}
        </span>
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={recorder.cancel}
          aria-label="Discard the recording"
          data-testid="notes-dictate-cancel"
        >
          <X />
        </Button>
        <Button
          variant="secondary"
          size="icon-sm"
          onClick={recorder.stop}
          aria-label="Stop recording"
          data-testid="notes-dictate-stop"
        >
          <Square />
        </Button>
      </div>
    )
  }

  return (
    <Button
      variant="ghost"
      size={size}
      className={className}
      onClick={() => void recorder.start()}
      disabled={recorder.state === "starting"}
      aria-label={label}
      title={
        lastCost !== null
          ? `Last recording cost ${lastCost} credits`
          : `About ${voice.data.credits_per_minute} credits a minute`
      }
      data-testid="notes-dictate"
    >
      <Mic />
      {size === "sm" && label}
    </Button>
  )
}
