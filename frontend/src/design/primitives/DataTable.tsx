import type { ReactNode } from "react"
import { ErrorState } from "./ErrorState"
import type { SurfaceState } from "./primitiveTypes"
import { Skeleton } from "./Skeleton"

export type DataTableColumn<Row> = {
  readonly id: string
  readonly header: string
  readonly render: (row: Row) => ReactNode
}

export type DataTableSort = {
  readonly columnId: string
  readonly direction: "ascending" | "descending"
  readonly disabled?: boolean
  readonly onSort: (columnId: string) => void
}

type DataTableProps<Row> = {
  readonly caption: string
  readonly columns: readonly DataTableColumn<Row>[]
  readonly rows: readonly Row[]
  readonly rowKey: (row: Row) => string
  readonly sort?: DataTableSort
  readonly state?: SurfaceState
  readonly onRetry?: () => void
}

export function DataTable<Row>({
  caption,
  columns,
  rows,
  rowKey,
  sort,
  state = "default",
  onRetry,
}: DataTableProps<Row>) {
  if (state === "loading") {
    return <Skeleton variant="table" label={`Loading ${caption}`} />
  }

  return (
    // biome-ignore lint/a11y/noNoninteractiveTabindex: Scrollable table regions require keyboard access.
    <section className="tableRegion" aria-label={`${caption} scroll area`} tabIndex={0}>
      <table className="dataTable">
        <caption>{caption}</caption>
        <thead>
          <tr>
            {columns.map((column) => {
              const direction = sort?.columnId === column.id ? sort.direction : "none"
              return (
                <th key={column.id} scope="col" aria-sort={sort ? direction : undefined}>
                  {sort ? (
                    <button
                      type="button"
                      disabled={sort.disabled}
                      onClick={() => sort.onSort(column.id)}
                    >
                      Sort by {column.header}
                    </button>
                  ) : (
                    column.header
                  )}
                </th>
              )
            })}
          </tr>
        </thead>
        <tbody>
          {state === "error" ? (
            <tr>
              <td colSpan={columns.length}>
                <ErrorState
                  title={`${caption} unavailable`}
                  code="TABLE_UNAVAILABLE"
                  detail="Exact values could not be loaded."
                  {...(onRetry ? { onRetry } : {})}
                />
              </td>
            </tr>
          ) : null}
          {state === "empty" || (state === "default" && rows.length === 0) ? (
            <tr>
              <td className="emptyMessage" colSpan={columns.length}>
                No rows available.
              </td>
            </tr>
          ) : null}
          {state !== "error" && state !== "empty"
            ? rows.map((row) => (
                <tr key={rowKey(row)} data-state={state}>
                  {columns.map((column) => (
                    <td key={column.id}>{column.render(row)}</td>
                  ))}
                </tr>
              ))
            : null}
        </tbody>
      </table>
    </section>
  )
}
