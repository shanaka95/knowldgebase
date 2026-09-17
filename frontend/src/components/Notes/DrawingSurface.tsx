import { getStroke } from "perfect-freehand"
import { useCallback, useRef, useState } from "react"

import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

/**
 * A drawing surface, in about as little code as one can be.
 *
 * `perfect-freehand` (4 kB, no dependencies) turns a list of points into the
 * outline of a stroke; everything else here is pointer events and an `<svg>`.
 * The alternative was tldraw or Excalidraw, each 500 kB to a megabyte with its
 * own document model and its own persistence, which would have fought the
 * version-and-409 contract the rest of a note saves through.
 *
 * Strokes are kept as points, not as an image. That is what lets a sketch be
 * reopened and drawn on a week later; the PNG is derived from them when it is
 * time to save, for the vision pass and for the card.
 */
export interface Stroke {
  points: [number, number, number][]
  color: string
  size: number
}

export const PALETTE = [
  { name: "Ink", value: "#111827" },
  { name: "Red", value: "#dc2626" },
  { name: "Blue", value: "#2563eb" },
  { name: "Green", value: "#16a34a" },
]

const SIZES = [
  { name: "Fine", value: 4 },
  { name: "Medium", value: 8 },
  { name: "Broad", value: 16 },
]

/** The canvas the strokes are drawn in, in its own coordinates. */
export const BOARD = { width: 1600, height: 1000 }

function toPath(stroke: Stroke): string {
  const outline = getStroke(stroke.points, {
    size: stroke.size,
    thinning: 0.6,
    smoothing: 0.5,
    streamline: 0.5,
    simulatePressure: true,
  })
  if (outline.length === 0) return ""
  const parts = outline.map(
    ([x, y], index) =>
      `${index === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`,
  )
  return `${parts.join(" ")} Z`
}

/** The whole drawing as an SVG document, which is what gets rasterised. */
export function toSvg(strokes: Stroke[]): string {
  const paths = strokes
    .map((stroke) => `<path d="${toPath(stroke)}" fill="${stroke.color}"/>`)
    .join("")
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" width="${BOARD.width}" ` +
    `height="${BOARD.height}" viewBox="0 0 ${BOARD.width} ${BOARD.height}">` +
    `<rect width="100%" height="100%" fill="#ffffff"/>${paths}</svg>`
  )
}

/**
 * A PNG of the drawing, on a white background.
 *
 * White rather than transparent on purpose: the picture is shown on cards and
 * read by a vision model, and black ink on transparency renders as black on
 * black in a dark theme and as nothing at all to some image pipelines.
 */
export function toPng(strokes: Stroke[]): Promise<Blob> {
  const svg = toSvg(strokes)
  const url = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`
  return new Promise((resolve, reject) => {
    const image = new Image()
    image.onload = () => {
      const canvas = document.createElement("canvas")
      canvas.width = BOARD.width
      canvas.height = BOARD.height
      const context = canvas.getContext("2d")
      if (!context) {
        reject(new Error("This browser cannot render the drawing"))
        return
      }
      context.drawImage(image, 0, 0, BOARD.width, BOARD.height)
      canvas.toBlob(
        (blob) =>
          blob
            ? resolve(blob)
            : reject(new Error("The drawing could not be saved")),
        "image/png",
      )
    }
    image.onerror = () => reject(new Error("The drawing could not be rendered"))
    image.src = url
  })
}

export function DrawingSurface({
  strokes,
  onChange,
  readOnly = false,
  className,
}: {
  strokes: Stroke[]
  onChange: (strokes: Stroke[]) => void
  readOnly?: boolean
  className?: string
}) {
  const svgRef = useRef<SVGSVGElement | null>(null)
  const [drawing, setDrawing] = useState<Stroke | null>(null)
  const [color, setColor] = useState(PALETTE[0].value)
  const [size, setSize] = useState(SIZES[1].value)

  const pointFrom = useCallback(
    (event: React.PointerEvent): [number, number, number] => {
      const box = svgRef.current?.getBoundingClientRect()
      if (!box) return [0, 0, 0.5]
      // Into the board's own coordinates, so a sketch drawn on a phone and
      // reopened on a desktop is the same sketch rather than a bigger one.
      return [
        ((event.clientX - box.left) / box.width) * BOARD.width,
        ((event.clientY - box.top) / box.height) * BOARD.height,
        event.pressure || 0.5,
      ]
    },
    [],
  )

  const start = (event: React.PointerEvent) => {
    if (readOnly || event.button !== 0) return
    event.currentTarget.setPointerCapture(event.pointerId)
    setDrawing({ points: [pointFrom(event)], color, size })
  }

  const extend = (event: React.PointerEvent) => {
    if (!drawing) return
    setDrawing({ ...drawing, points: [...drawing.points, pointFrom(event)] })
  }

  const finish = () => {
    if (!drawing) return
    if (drawing.points.length > 1) onChange([...strokes, drawing])
    setDrawing(null)
  }

  const visible = drawing ? [...strokes, drawing] : strokes

  return (
    <div className={cn("flex min-w-0 flex-col gap-2", className)}>
      {!readOnly && (
        <div
          className="flex min-w-0 flex-wrap items-center gap-2"
          data-testid="notes-drawing-tools"
        >
          <div className="flex items-center gap-1">
            {PALETTE.map((option) => (
              <button
                key={option.value}
                type="button"
                aria-label={option.name}
                aria-pressed={color === option.value}
                onClick={() => setColor(option.value)}
                className={cn(
                  "size-6 rounded-full border-2",
                  color === option.value
                    ? "border-foreground"
                    : "border-transparent",
                )}
                style={{ backgroundColor: option.value }}
              />
            ))}
          </div>
          <div className="flex items-center gap-1">
            {SIZES.map((option) => (
              <Button
                key={option.value}
                variant={size === option.value ? "secondary" : "ghost"}
                size="sm"
                onClick={() => setSize(option.value)}
              >
                {option.name}
              </Button>
            ))}
          </div>
          <div className="ms-auto flex items-center gap-1">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onChange(strokes.slice(0, -1))}
              disabled={strokes.length === 0}
              data-testid="notes-drawing-undo"
            >
              Undo
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onChange([])}
              disabled={strokes.length === 0}
              data-testid="notes-drawing-clear"
            >
              Clear
            </Button>
          </div>
        </div>
      )}

      {/* touch-action: none is not optional. Without it a finger scrolls the
          page instead of drawing on it, and the surface is unusable on a
          phone - which is where most sketches get made. */}
      <svg
        ref={svgRef}
        viewBox={`0 0 ${BOARD.width} ${BOARD.height}`}
        className={cn(
          "w-full touch-none rounded-lg border bg-white",
          readOnly ? "cursor-default" : "cursor-crosshair",
        )}
        style={{ aspectRatio: `${BOARD.width} / ${BOARD.height}` }}
        onPointerDown={start}
        onPointerMove={extend}
        onPointerUp={finish}
        onPointerLeave={finish}
        onPointerCancel={finish}
        role="img"
        aria-label="Drawing"
        data-testid="notes-drawing-surface"
      >
        <title>Drawing</title>
        {visible.map((stroke, index) => (
          <path
            // Strokes are only ever appended to or dropped from the end, so
            // the index is stable for the life of a stroke.
            key={index}
            d={toPath(stroke)}
            fill={stroke.color}
          />
        ))}
      </svg>
    </div>
  )
}
