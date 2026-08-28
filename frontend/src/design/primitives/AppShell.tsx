import type { LucideIcon } from "lucide-react"
import type { ReactNode } from "react"

export type AppNavigationItem = {
  readonly label: string
  readonly href: string
  readonly icon: LucideIcon
  readonly active: boolean
  readonly disabled?: boolean
  readonly highlighted?: boolean
  readonly focus?: boolean
}

type AppShellProps = {
  readonly navigation: readonly AppNavigationItem[]
  readonly preview?: boolean
  readonly previewLabel?: string
  readonly commandBar?: ReactNode
  readonly contextRail?: ReactNode
  readonly evidenceRail?: ReactNode
  readonly children: ReactNode
}

function navigationTabIndex(item: AppNavigationItem, hasFocusTarget: boolean): number | undefined {
  if (item.disabled) return -1
  if (!hasFocusTarget) return undefined
  return item.focus ? 0 : -1
}

export function AppShell({
  navigation,
  preview = false,
  previewLabel,
  commandBar,
  contextRail,
  evidenceRail,
  children,
}: AppShellProps) {
  const hasFocusTarget = navigation.some((item) => item.focus)
  const routeBody = preview ? (
    <div className="routeBody showcaseShellRoute" data-layout="preview-route">
      {children}
    </div>
  ) : (
    <main className="routeBody" id="main-content" tabIndex={-1}>
      {children}
    </main>
  )

  return (
    <div className="appShell" data-preview={preview ? "true" : undefined}>
      {preview ? null : (
        <a className="skipLink" href="#main-content">
          Skip to main content
        </a>
      )}
      <nav
        className="primaryNav"
        aria-label={preview ? (previewLabel ?? "Preview navigation") : "Primary"}
      >
        <ul className="primaryNavList">
          {navigation.map((item) => {
            const Icon = item.icon
            return (
              <li key={item.href}>
                <a
                  className="primaryNavLink"
                  href={item.disabled ? undefined : item.href}
                  aria-current={item.active ? "page" : undefined}
                  aria-disabled={item.disabled || undefined}
                  data-highlighted={item.highlighted || undefined}
                  tabIndex={navigationTabIndex(item, hasFocusTarget)}
                >
                  <Icon aria-hidden="true" />
                  <span>{item.label}</span>
                </a>
              </li>
            )
          })}
        </ul>
      </nav>
      <header className="commandBar">{commandBar ?? <span>Console foundation</span>}</header>
      <div className="appShellBody">
        {contextRail ? (
          <aside className="contextRail" aria-label="Context rail">
            {contextRail}
          </aside>
        ) : null}
        {routeBody}
        {evidenceRail ? (
          <aside className="evidenceRail" aria-label="Evidence rail">
            {evidenceRail}
          </aside>
        ) : null}
      </div>
    </div>
  )
}
