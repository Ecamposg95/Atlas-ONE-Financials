import type { ReactNode } from 'react'
import { BrandMark } from '@/components/ui/BrandMark'

/** Marco compartido de las pantallas de acceso: marca arriba, una tarjeta, un enlace abajo.
 *  Lockup de marca Atlas: símbolo + "Atlas" + nombre del producto en tono apagado. */
export function AuthShell({ children, footer }: { children: ReactNode; footer?: ReactNode }) {
  return (
    <div className="auth-bg flex min-h-full items-center justify-center px-4 py-10">
      <div className="w-full max-w-[400px]">
        <header className="fin-rise mb-7 text-center">
          <div className="flex items-center justify-center gap-3 text-ink">
            <BrandMark className="h-8 w-auto" />
            <div className="font-display text-[28px] font-light leading-none tracking-[-0.035em]">
              <span className="font-medium">Atlas</span> <span className="text-ink-soft">ONE Financials</span>
            </div>
          </div>
          <p className="mt-3 font-mono text-[10px] uppercase tracking-[0.22em] text-muted">
            Administración financiera y contable
          </p>
        </header>

        <div className="fin-rise fin-rise-late auth-card p-7 shadow-float">
          {children}
        </div>

        {footer ? (
          <p className="fin-rise fin-rise-late mt-5 text-center text-sm text-ink-soft">{footer}</p>
        ) : null}
      </div>
    </div>
  )
}
