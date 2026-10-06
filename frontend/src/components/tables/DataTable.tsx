import clsx from 'clsx'
import type { ReactNode } from 'react'

export interface Column<T> {
  key: string
  header: string
  render: (row: T) => ReactNode
  align?: 'left' | 'right' | 'center'
  className?: string
}

export default function DataTable<T>({
  columns,
  rows,
  rowKey,
  onRowClick,
}: {
  columns: Column<T>[]
  rows: T[]
  rowKey: (row: T) => string
  onRowClick?: (row: T) => void
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[560px] border-collapse text-left text-sm">
        <thead>
          <tr className="border-b border-[var(--color-border)]">
            {columns.map((c) => (
              <th
                key={c.key}
                className={clsx(
                  'whitespace-nowrap px-3 py-2 text-xs font-semibold uppercase tracking-wide text-[var(--color-text-muted)]',
                  c.align === 'right' && 'text-right',
                  c.align === 'center' && 'text-center',
                )}
              >
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={rowKey(row)}
              onClick={() => onRowClick?.(row)}
              className={clsx(
                'border-b border-[var(--color-border)]/60 last:border-0',
                onRowClick && 'cursor-pointer hover:bg-black/[0.03]',
              )}
            >
              {columns.map((c) => (
                <td
                  key={c.key}
                  className={clsx(
                    'whitespace-nowrap px-3 py-2.5 text-[var(--color-text-secondary)]',
                    c.align === 'right' && 'text-right',
                    c.align === 'center' && 'text-center',
                    c.className,
                  )}
                >
                  {c.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length === 0 && (
        <div className="py-10 text-center text-xs text-[var(--color-text-muted)]">No data available.</div>
      )}
    </div>
  )
}
