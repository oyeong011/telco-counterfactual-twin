import type { LucideIcon } from "lucide-react"
import type { ReactNode } from "react"

export type AppNavigationItem = {
  readonly label: string
  readonly href: string
  readonly icon: LucideIcon
  readonly active: boolean
  readonly disabled?: boolean
}

type AppShellProps = {
  readonly navigation: readonly AppNavigationItem[]
  readonly commandBar?: ReactNode
  readonly contextRail?: ReactNode
  readonly evidenceRail?: ReactNode
  readonly children: ReactNode
}

export function AppShell({
  navigation,
  commandBar,
  contextRail,
  evidenceRail,
  children,
}: AppShellProps) {
  return (
    <div className="appShell">
      <a className="skipLink" href="#main-content">
        Skip to main content
      </a>
      <nav className="primaryNav" aria-label="Primary">
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
                  tabIndex={item.disabled ? -1 : undefined}
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
        {contextRail ? <aside className="contextRail">{contextRail}</aside> : null}
        <main className="routeBody" id="main-content" tabIndex={-1}>
          {children}
        </main>
        {evidenceRail ? <aside className="evidenceRail">{evidenceRail}</aside> : null}
      </div>
    </div>
  )
}
