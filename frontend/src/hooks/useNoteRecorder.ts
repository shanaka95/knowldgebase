import { useCallback, useEffect, useRef, useState } from "react"

/**
 * One recording, from the microphone to a Blob.
 *
 * `MediaRecorder` is the whole implementation; what this adds is the things
 * that go wrong around it. The stream's tracks are stopped on every path out,
 * including unmount, because a track left running keeps the browser's recording
 * indicator lit and the microphone open - which reads, correctly, as the app
 * still listening. Recording stops itself at the cap rather than trusting the
 * person to, so the request is bounded before it is sent rather than refused
 * after the upload.
 *
 * Nothing here is stored. The Blob lives until the transcript comes back.
 */
export type RecorderState = "idle" | "starting" | "recording" | "stopping"

export interface Recording {
  blob: Blob
  /** What the clock said, which is what the duration cap is enforced on. */
  seconds: number
  mimeType: string
}

/** The first type this browser will actually record. Safari is the odd one. */
function pickMimeType(): string {
  const candidates = [
    "audio/webm;codecs=opus",
    "audio/webm",
    "audio/mp4",
    "audio/ogg;codecs=opus",
  ]
  if (typeof MediaRecorder === "undefined") return ""
  return candidates.find((type) => MediaRecorder.isTypeSupported(type)) ?? ""
}

export function recorderSupported(): boolean {
  return (
    typeof MediaRecorder !== "undefined" &&
    typeof navigator !== "undefined" &&
    !!navigator.mediaDevices?.getUserMedia
  )
}

export function useNoteRecorder({
  maxSeconds,
  onFinished,
  onError,
}: {
  maxSeconds: number
  onFinished: (recording: Recording) => void
  onError?: (message: string) => void
}) {
  const [state, setState] = useState<RecorderState>("idle")
  const [seconds, setSeconds] = useState(0)
  // 0 to 1, for the meter. Its only job is to show that the microphone is
  // hearing something: a silent bar is how somebody finds out their headset is
  // muted before they have talked for a minute.
  const [level, setLevel] = useState(0)

  const recorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const streamRef = useRef<MediaStream | null>(null)
  const audioRef = useRef<AudioContext | null>(null)
  const frameRef = useRef<number | null>(null)
  const tickRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const startedRef = useRef(0)
  const keepRef = useRef(true)

  const release = useCallback(() => {
    if (frameRef.current !== null) cancelAnimationFrame(frameRef.current)
    frameRef.current = null
    if (tickRef.current !== null) clearInterval(tickRef.current)
    tickRef.current = null
    void audioRef.current?.close().catch(() => {})
    audioRef.current = null
    for (const track of streamRef.current?.getTracks() ?? []) track.stop()
    streamRef.current = null
    recorderRef.current = null
    setLevel(0)
  }, [])

  // The microphone must not outlive the component that opened it.
  useEffect(() => release, [release])

  const stop = useCallback((keep = true) => {
    keepRef.current = keep
    const recorder = recorderRef.current
    if (!recorder || recorder.state === "inactive") return
    setState("stopping")
    recorder.stop()
  }, [])

  const start = useCallback(async () => {
    if (!recorderSupported()) {
      onError?.("This browser cannot record audio")
      return
    }
    setState("starting")
    let stream: MediaStream
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch (error) {
      setState("idle")
      // The overwhelmingly common case, and the one where a generic failure
      // message sends people to the wrong place entirely.
      const denied =
        error instanceof DOMException && error.name === "NotAllowedError"
      onError?.(
        denied
          ? "Your browser is blocking the microphone for this site"
          : "No microphone was available",
      )
      return
    }

    streamRef.current = stream
    chunksRef.current = []
    keepRef.current = true
    startedRef.current = Date.now()
    setSeconds(0)

    const mimeType = pickMimeType()
    const recorder = new MediaRecorder(
      stream,
      mimeType ? { mimeType } : undefined,
    )
    recorderRef.current = recorder

    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) chunksRef.current.push(event.data)
    }
    recorder.onstop = () => {
      const elapsed = Math.round((Date.now() - startedRef.current) / 1000)
      const blob = new Blob(chunksRef.current, {
        type: recorder.mimeType || "audio/webm",
      })
      chunksRef.current = []
      release()
      setState("idle")
      if (keepRef.current && blob.size > 0) {
        onFinished({
          blob,
          seconds: Math.max(1, Math.min(elapsed, maxSeconds)),
          mimeType: recorder.mimeType || "audio/webm",
        })
      }
    }

    // A meter, not a waveform: one number a frame, read off the time domain.
    try {
      const context = new AudioContext()
      audioRef.current = context
      const analyser = context.createAnalyser()
      analyser.fftSize = 512
      context.createMediaStreamSource(stream).connect(analyser)
      const samples = new Uint8Array(analyser.frequencyBinCount)
      const read = () => {
        analyser.getByteTimeDomainData(samples)
        let peak = 0
        for (const sample of samples) {
          peak = Math.max(peak, Math.abs(sample - 128) / 128)
        }
        setLevel(peak)
        frameRef.current = requestAnimationFrame(read)
      }
      frameRef.current = requestAnimationFrame(read)
    } catch {
      // A meter is a nicety. Recording without one is still recording.
    }

    tickRef.current = setInterval(() => {
      const elapsed = Math.round((Date.now() - startedRef.current) / 1000)
      setSeconds(elapsed)
      if (elapsed >= maxSeconds) stop(true)
    }, 250)

    recorder.start()
    setState("recording")
  }, [maxSeconds, onError, onFinished, release, stop])

  return {
    state,
    seconds,
    level,
    recording: state === "recording",
    start,
    stop: () => stop(true),
    cancel: () => stop(false),
    remaining: Math.max(0, maxSeconds - seconds),
  }
}
