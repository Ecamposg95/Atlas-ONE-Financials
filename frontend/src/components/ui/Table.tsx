import type { ReactNode } from 'react'

/** Celda de la columna fija de `Table stickyLast`: fondo opaco para tapar lo que pasa debajo. */
export const STICKY_CELL = 'sticky right-0 bg-surface'

export function Table({
  headers,
  children,
  footer,
  secondary,
  stickyLast = false,
}: {
  headers: (string | ReactNode)[]
  children: ReactNode
  footer?: ReactNode
  /** Columnas (índice base 1) que se ocultan en pantallas chicas: en un teléfono
   *  vale más ver cinco columnas legibles que nueve tras un scroll lateral. */
  secondary?: number[]
  /** La última columna (acciones) queda fija a la derecha: si la tabla no cabe,
   *  se desplaza el resto y el botón sigue a la vista. Sus celdas llevan `STICKY_CELL`. */
  stickyLast?: boolean
}) {
  return (
    <div className="rounded-xl border border-border bg-surface shadow-card">
      <div className="overflow-x-auto">
        <table className="w-full text-sm" data-secondary={secondary?.join(' ')}>
          <thead>
            <tr className="border-b border-border text-left">
              {headers.map((header, index) => (
                <th
                  key={index}
                  className={`whitespace-nowrap px-4 py-2.5 text-[11px] font-semibold uppercase tracking-wider text-muted ${
                    stickyLast && index === headers.length - 1 ? STICKY_CELL : ''
                  }`}
                >
                  {header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-border">{children}</tbody>
        </table>
      </div>
      {footer}
    </div>
  )
}

export function Card({
  children,
  className = '',
  onClick,
}: {
  children: ReactNode
  className?: string
  onClick?: () => void
}) {
  return (
    <div
      className={`rounded-xl border border-border bg-surface p-5 shadow-card ${className}`}
      onClick={onClick}
      // Una tarjeta clicable también se abre con teclado; una estática no roba el tab.
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={
        onClick
          ? (event) => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault()
                onClick()
              }
            }
          : undefined
      }
    >
      {children}
    </div>
  )
}
