import { useMutation, useQuery } from "@tanstack/react-query"

import { type NoteTranscript, UserNotesService } from "@/client"

/**
 * Whether this deployment can take dictation, and on what terms.
 *
 * Asked once and kept: a model is configured at deploy time, so re-reading it
 * per render would be a request to learn something that cannot have changed.
 */
export function voiceSettingsQuery() {
  return {
    queryKey: ["user-notes", "voice"] as const,
    queryFn: async () => (await UserNotesService.notesReadVoiceSettings()).data,
    staleTime: 10 * 60 * 1000,
  }
}

export function useVoiceSettings() {
  return useQuery(voiceSettingsQuery())
}

export function useTranscribe() {
  return useMutation({
    mutationFn: async ({
      blob,
      seconds,
      mimeType,
      language,
    }: {
      blob: Blob
      seconds: number
      mimeType: string
      language?: string | null
    }): Promise<NoteTranscript | undefined> => {
      // The extension matters: some providers sniff the container from the
      // filename rather than the part's content type.
      const extension = mimeType.includes("mp4")
        ? "m4a"
        : mimeType.includes("ogg")
          ? "ogg"
          : "webm"
      const response = await UserNotesService.notesTranscribe({
        body: {
          file: new File([blob], `recording.${extension}`, { type: mimeType }),
          seconds,
          language: language ?? null,
        },
      })
      return response.data
    },
  })
}
