import {
  Ban,
  CheckCircle2,
  CircleAlert,
  CircleDot,
  Clock3,
  FlaskConical,
  Info,
  LoaderCircle,
  type LucideIcon,
} from "lucide-react"

export type StatusTone =
  | "neutral"
  | "info"
  | "proof"
  | "warning"
  | "danger"
  | "loading"
  | "demo"
  | "stale"
  | "rejected"
  | "approved"

type StatusChipProps = {
  readonly tone: StatusTone
  readonly label: string
  readonly metadata?: string
  readonly disabled?: boolean
  readonly pressed?: boolean
  readonly onPress?: () => void
}

const TONE_ICONS = {
  neutral: CircleDot,
  info: Info,
  proof: CheckCircle2,
  warning: CircleAlert,
  danger: Ban,
  loading: LoaderCircle,
  demo: FlaskConical,
  stale: Clock3,
  rejected: Ban,
  approved: CheckCircle2,
} satisfies Record<StatusTone, LucideIcon>

export function StatusChip({
  tone,
  label,
  metadata,
  disabled = false,
  pressed = false,
  onPress,
}: StatusChipProps) {
  const Icon = TONE_ICONS[tone]
  const content = (
    <>
      <Icon aria-hidden="true" className="statusChipIcon" />
      <span>{label}</span>
      {metadata ? <span className="statusChipMeta">{metadata}</span> : null}
    </>
  )

  if (onPress) {
    return (
      <button
        type="button"
        className="statusChip statusChipInteractive"
        data-tone={tone}
        disabled={disabled}
        aria-pressed={pressed}
        onClick={onPress}
      >
        {content}
      </button>
    )
  }

  return (
    <span className="statusChip" data-tone={tone} aria-disabled={disabled || undefined}>
      {content}
    </span>
  )
}
