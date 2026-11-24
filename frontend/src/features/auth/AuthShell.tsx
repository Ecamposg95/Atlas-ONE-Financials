import type { ReactNode } from 'react'

/** Marco compartido de las pantallas de acceso: marca arriba, una tarjeta, un enlace abajo.
 *  Sin ícono: el logotipo ya dice Atlas Financials — repetir la marca en un badge era redundante. */
export function AuthShell({ children, footer }: { children: ReactNode; footer?: ReactNode }) {
  return (
    <div className="auth-bg flex min-h-full items-center justify-center px-4 py-10">
      <div className="w-full max-w-[400px]">
        <header className="fin-rise mb-7 text-center">
          <div className="font-display text-[32px] font-extrabold leading-none tracking-[-0.04em] text-rail-ink">
            Atlas ONE Financials
          </div>
          <p className="figures mt-2.5 text-[10px] uppercase tracking-[0.24em] text-rail-muted">
            Administración financiera y contable
          </p>
        </header>

        <div className="fin-rise fin-rise-late rounded-xl border border-border bg-surface p-7 shadow-float">
          {children}
        </div>

        {footer ? (
          <p className="fin-rise fin-rise-late mt-5 text-center text-sm text-rail-muted">{footer}</p>
        ) : null}
      </div>
    </div>
  )
}
