import { MessageSquare } from "lucide-react"

import { cn } from "@/lib/utils"

/**
 * Each messaging platform's own mark.
 *
 * People recognise these long before they read the label, and a row of
 * identical speech bubbles makes the reader work for something the logo says
 * instantly. Drawn from each platform's published glyph and rendered in brand
 * colour, since a WhatsApp green that is not WhatsApp's green reads as a
 * mistake.
 *
 * Anything without a mark here falls back to a neutral bubble rather than a
 * blank, so a channel added later still renders.
 */

type IconProps = { className?: string }

function WhatsAppIcon({ className }: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      className={cn("size-5", className)}
      fill="#25D366"
      aria-hidden="true"
      focusable="false"
    >
      <path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51a12.8 12.8 0 0 0-.57-.01c-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.71.306 1.263.489 1.694.625.712.227 1.36.195 1.872.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347z" />
      <path d="M20.52 3.449C18.24 1.245 15.24 0 12.045 0 5.463 0 .104 5.359.101 11.944c0 2.096.549 4.14 1.595 5.945L0 24l6.305-1.654a11.9 11.9 0 0 0 5.71 1.454h.006c6.585 0 11.946-5.36 11.949-11.945 0-3.191-1.24-6.191-3.495-8.446M12.02 21.785h-.004a9.9 9.9 0 0 1-5.031-1.378l-.361-.214-3.741.981.999-3.648-.235-.374a9.86 9.86 0 0 1-1.511-5.26c.002-5.45 4.437-9.884 9.889-9.884a9.82 9.82 0 0 1 6.988 2.898 9.83 9.83 0 0 1 2.893 6.994c-.003 5.45-4.437 9.885-9.886 9.885" />
    </svg>
  )
}

function TelegramIcon({ className }: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      className={cn("size-5", className)}
      aria-hidden="true"
      focusable="false"
    >
      <circle cx="12" cy="12" r="12" fill="#29A9EB" />
      <path
        fill="#fff"
        d="M5.491 11.74l11.57-4.461c.537-.194 1.006.131.832.943l.001-.001-1.97 9.281c-.146.658-.537.818-1.084.508l-3-2.211-1.447 1.394c-.16.16-.295.295-.605.295l.213-3.053 5.56-5.023c.242-.213-.054-.333-.373-.121l-6.871 4.326-2.962-.924c-.643-.204-.657-.643.136-.953z"
      />
    </svg>
  )
}

function SlackIcon({ className }: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      className={cn("size-5", className)}
      aria-hidden="true"
      focusable="false"
    >
      <path
        fill="#E01E5A"
        d="M5.042 15.165a2.53 2.53 0 0 1-2.52 2.523A2.53 2.53 0 0 1 0 15.165a2.53 2.53 0 0 1 2.522-2.52h2.52zm1.271 0a2.53 2.53 0 0 1 2.521-2.52 2.53 2.53 0 0 1 2.521 2.52v6.313A2.53 2.53 0 0 1 8.834 24a2.53 2.53 0 0 1-2.521-2.522z"
      />
      <path
        fill="#36C5F0"
        d="M8.834 5.042a2.53 2.53 0 0 1-2.521-2.52A2.53 2.53 0 0 1 8.834 0a2.53 2.53 0 0 1 2.521 2.522v2.52zm0 1.271a2.53 2.53 0 0 1 2.521 2.521 2.53 2.53 0 0 1-2.521 2.521H2.522A2.53 2.53 0 0 1 0 8.834a2.53 2.53 0 0 1 2.522-2.521z"
      />
      <path
        fill="#2EB67D"
        d="M18.956 8.834a2.53 2.53 0 0 1 2.522-2.521A2.53 2.53 0 0 1 24 8.834a2.53 2.53 0 0 1-2.522 2.521h-2.522zm-1.268 0a2.53 2.53 0 0 1-2.523 2.521 2.53 2.53 0 0 1-2.52-2.521V2.522A2.53 2.53 0 0 1 15.165 0a2.53 2.53 0 0 1 2.523 2.522z"
      />
      <path
        fill="#ECB22E"
        d="M15.165 18.956a2.53 2.53 0 0 1 2.523 2.522A2.53 2.53 0 0 1 15.165 24a2.53 2.53 0 0 1-2.52-2.522v-2.522zm0-1.268a2.53 2.53 0 0 1-2.52-2.523 2.53 2.53 0 0 1 2.52-2.52h6.313A2.53 2.53 0 0 1 24 15.165a2.53 2.53 0 0 1-2.522 2.523z"
      />
    </svg>
  )
}

function DiscordIcon({ className }: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      className={cn("size-5", className)}
      fill="#5865F2"
      aria-hidden="true"
      focusable="false"
    >
      <path d="M20.317 4.37a19.8 19.8 0 0 0-4.885-1.515.07.07 0 0 0-.079.036c-.21.375-.444.865-.608 1.25a18.3 18.3 0 0 0-5.487 0 12 12 0 0 0-.617-1.25.08.08 0 0 0-.079-.036A19.7 19.7 0 0 0 3.677 4.37a.07.07 0 0 0-.032.027C.533 9.046-.32 13.58.099 18.057a.08.08 0 0 0 .031.055 19.9 19.9 0 0 0 5.993 3.03.08.08 0 0 0 .084-.028c.462-.63.874-1.295 1.226-1.994a.076.076 0 0 0-.041-.106 13 13 0 0 1-1.872-.892.077.077 0 0 1-.008-.128 10 10 0 0 0 .372-.292.07.07 0 0 1 .078-.01c3.928 1.793 8.18 1.793 12.062 0a.07.07 0 0 1 .079.009q.18.15.372.293a.077.077 0 0 1-.006.127 12.3 12.3 0 0 1-1.873.891.077.077 0 0 0-.041.107c.36.698.772 1.362 1.225 1.993a.08.08 0 0 0 .084.028 19.8 19.8 0 0 0 6.002-3.03.08.08 0 0 0 .032-.054c.5-5.177-.838-9.674-3.549-13.66a.06.06 0 0 0-.031-.03M8.02 15.331c-1.183 0-2.157-1.085-2.157-2.419s.955-2.419 2.157-2.419c1.21 0 2.176 1.096 2.157 2.42 0 1.333-.955 2.418-2.157 2.418m7.975 0c-1.183 0-2.157-1.085-2.157-2.419s.955-2.419 2.157-2.419c1.21 0 2.176 1.096 2.157 2.42 0 1.333-.946 2.418-2.157 2.418" />
    </svg>
  )
}

const ICONS: Record<string, (props: IconProps) => React.ReactElement> = {
  whatsapp: WhatsAppIcon,
  telegram: TelegramIcon,
  slack: SlackIcon,
  discord: DiscordIcon,
}

export function ChannelIcon({
  channel,
  className,
}: {
  channel: string
  className?: string
}) {
  const Icon = ICONS[channel]
  if (!Icon) {
    return (
      <MessageSquare
        className={cn("size-5 text-muted-foreground", className)}
        aria-hidden="true"
      />
    )
  }
  return <Icon className={className} />
}
