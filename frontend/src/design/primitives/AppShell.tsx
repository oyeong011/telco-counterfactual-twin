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
  readonly navigationLabel?: string
  readonly contentId?: string
  readonly commandBar?: ReactNode
  readonly navigationContent?: ReactNode
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
  navigationLabel = "Primary",
  contentId = "main-content",
  commandBar,
  navigationContent,
  contextRail,
  evidenceRail,
  children,
}: AppShellProps) {
  const hasFocusTarget = navigation.some((item) => item.focus)

  return (
    <div className="appShell">
      <a className="skipLink" href={`#${contentId}`}>
        Skip to main content
      </a>
      <nav className="primaryNav" aria-label={navigationLabel}>
        <ul className="primaryNavList">
          {navigationContent ??
            navigation.map((item) => {
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
        <main className="routeBody" id={contentId} tabIndex={-1}>
          {children}
        </main>
        {evidenceRail ? (
          <aside className="evidenceRail" aria-label="Evidence rail">
            {evidenceRail}
          </aside>
        ) : null}
      </div>
    </div>
  )
}
