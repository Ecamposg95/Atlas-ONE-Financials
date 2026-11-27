/** R2·HU-01: si el gasto que se captura coincide en proveedor y monto con una
 *  cuenta por pagar abierta, probablemente es su pago. Capturarlo como gasto
 *  suelto lo contaría dos veces y la cuenta seguiría abierta. */

import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api } from '@/api/client'
import { formatDate, formatMoney } from '@/lib/format'
import type { Debt, Page } from '@/types/api'

function sameAmount(a: string | number, b: number): boolean {
  return Math.abs(Number(a) - b) < 0.005
}

export function PayableMatchNotice({ vendorId, amount }: { vendorId: string; amount: string }) {
  const value = Number(amount)
  const enabled = Boolean(vendorId) && Number.isFinite(value) && value > 0

  const { data } = useQuery({
    queryKey: ['payables', 'unpaid-by-vendor', vendorId],
    queryFn: async () =>
      (
        await api.get<Page<Debt>>('/payables', {
          params: { vendor_id: vendorId, status: 'UNPAID', limit: 50 },
        })
      ).data.items,
    enabled,
    staleTime: 30_000,
  })

  if (!enabled) return null
  const match = (data ?? []).find((debt) => sameAmount(debt.balance, value) || sameAmount(debt.amount, value))
  if (!match) return null

  return (
    <div className="rounded-lg border border-warn/40 bg-warn/10 px-3 py-2 text-sm" role="status">
      <p>
        Este proveedor tiene una cuenta por pagar abierta por{' '}
        <span className="figures font-medium">{formatMoney(match.balance)}</span> ({match.description}, vence{' '}
        {formatDate(match.due_date)}).
      </p>
      <p className="mt-1 text-muted">
        Si este gasto es su pago, regístralo desde la cuenta para no contarlo dos veces.{' '}
        <Link to={`/por-pagar?open=${match.id}`} className="font-medium text-accent underline-offset-2 hover:underline">
          Ir a la cuenta
        </Link>
      </p>
    </div>
  )
}
