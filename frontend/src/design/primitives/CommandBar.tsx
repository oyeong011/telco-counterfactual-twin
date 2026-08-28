import type { ReactNode } from "react"
import { StatusChip, type StatusTone } from "./StatusChip"

type CommandBarStatus = {
  readonly tone: StatusTone
  readonly label: string
  readonly metadata?: string
}

type CommandBarProps = {
  readonly title: string
  readonly status?: CommandBarStatus
  readonly actions?: ReactNode
  readonly children?: ReactNode
  readonly announcement?: string
}

export function CommandBar({ title, status, actions, children, announcement }: CommandBarProps) {
  return (
    <div className="commandBarContent">
      <div className="commandBarGroup">
        <h1 className="commandBarTitle">{title}</h1>
        {status ? (
          <StatusChip
            tone={status.tone}
            label={status.label}
            {...(status.metadata ? { metadata: status.metadata } : {})}
          />
        ) : null}
        {children}
      </div>
      {actions ? <div className="commandBarActions">{actions}</div> : null}
      <span className="visuallyHidden" aria-live="polite">
        {announcement}
      </span>
    </div>
  )
}
