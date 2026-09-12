import { useQuery } from "@tanstack/react-query"
import { Check, ChevronsUpDown, Plus, Tag, X } from "lucide-react"
import { useState } from "react"

import { Button } from "@/components/ui/button"
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/components/ui/command"
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover"
import { cn } from "@/lib/utils"
import { documentTypesQuery } from "@/queries/documents"

/** The backend caps a type at 60 characters; stop typing rather than 422. */
const MAX_LENGTH = 60

interface DocumentTypePickerProps {
  value: string | null
  onChange: (value: string | null) => void
  disabled?: boolean
  className?: string
}

/**
 * Picks the kind of page this is. The list is a suggestion, not a vocabulary:
 * anything typed that does not exist yet can be used as a new type.
 */
export function DocumentTypePicker({
  value,
  onChange,
  disabled,
  className,
}: DocumentTypePickerProps) {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState("")
  const { data } = useQuery({ ...documentTypesQuery(), enabled: open })

  const types = data?.data ?? []
  const typed = search.trim()
  const exists = types.some((t) => t.name.toLowerCase() === typed.toLowerCase())

  const choose = (name: string | null) => {
    onChange(name)
    setSearch("")
    setOpen(false)
  }

  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        setOpen(next)
        if (!next) setSearch("")
      }}
    >
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="outline"
          size="xs"
          disabled={disabled}
          role="combobox"
          aria-expanded={open}
          className={cn(
            "max-w-[14rem] font-normal",
            !value && "border-dashed text-muted-foreground",
            className,
          )}
          data-testid="document-type-trigger"
        >
          <Tag />
          <span className="truncate">{value ?? "Add type"}</span>
          <ChevronsUpDown className="opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        className="w-64 p-0"
        data-testid="document-type-popover"
      >
        <Command>
          <CommandInput
            placeholder="Search or create a type…"
            value={search}
            onValueChange={setSearch}
            maxLength={MAX_LENGTH}
            data-testid="document-type-input"
          />
          <CommandList>
            {typed === "" && <CommandEmpty>No types yet.</CommandEmpty>}
            {typed !== "" && !exists && (
              <CommandGroup>
                <CommandItem
                  value={typed}
                  onSelect={() => choose(typed)}
                  data-testid="document-type-create"
                >
                  <Plus />
                  <span className="truncate">Use “{typed}”</span>
                </CommandItem>
              </CommandGroup>
            )}
            <CommandGroup>
              {types.map((type) => (
                <CommandItem
                  key={type.name}
                  value={type.name}
                  onSelect={() => choose(type.name)}
                  data-testid="document-type-option"
                >
                  <Check
                    className={cn(
                      "text-foreground",
                      value === type.name ? "opacity-100" : "opacity-0",
                    )}
                  />
                  <span className="truncate">{type.name}</span>
                  {(type.count ?? 0) > 0 && (
                    <span className="ml-auto text-xs text-muted-foreground">
                      {type.count}
                    </span>
                  )}
                </CommandItem>
              ))}
            </CommandGroup>
            {value && (
              <>
                <CommandSeparator />
                <CommandGroup>
                  <CommandItem
                    value="__clear__"
                    onSelect={() => choose(null)}
                    data-testid="document-type-clear"
                  >
                    <X />
                    No type
                  </CommandItem>
                </CommandGroup>
              </>
            )}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  )
}

export default DocumentTypePicker
