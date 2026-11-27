import { SelectInput } from '@/components/ui/Field'
import { formatMoney } from '@/lib/format'
import { splitTotal, TAX_OPTIONS, TAX_RATES, defaultTreatment } from '@/lib/taxes'
import type { TaxTreatment } from '@/types/api'

/** Selector de IVA con el desglose en vivo: el usuario captura el total del
 *  ticket y ve de inmediato en qué se separa.
 *
 *  Con `onTaxChange` (R2·HU-05) distingue tasa 0, exento, no objeto y
 *  sin clasificar; sin él, sólo la tasa (reglas recurrentes). */
export function TaxSelect({
  total,
  rate,
  onRateChange,
  treatment,
  onTaxChange,
}: {
  total: string
  rate: string
  onRateChange: (rate: string) => void
  treatment?: TaxTreatment
  /** Tasa y tratamiento en un solo cambio (dos setState seguidos se pisarían). */
  onTaxChange?: (rate: string, treatment: TaxTreatment) => void
}) {
  const breakdown = splitTotal(total, rate)
  const withTreatment = Boolean(onTaxChange)
  // "0.1600" de la organización y "0.16" de la opción son la misma tasa.
  const current = `${Number(rate) > 0 ? String(Number(rate)) : '0'}|${treatment ?? defaultTreatment(rate)}`
  return (
    <div>
      {withTreatment ? (
        <SelectInput
          label="Impuesto"
          options={TAX_OPTIONS}
          value={current}
          onChange={(event) => {
            const [nextRate, nextTreatment] = event.target.value.split('|')
            if (onTaxChange) onTaxChange(nextRate, nextTreatment as TaxTreatment)
            else onRateChange(nextRate)
          }}
        />
      ) : (
        <SelectInput
          label="Impuesto"
          options={TAX_RATES}
          value={rate}
          onChange={(event) => onRateChange(event.target.value)}
        />
      )}
      {breakdown.tax > 0 ? (
        <p className="mt-1 text-xs text-muted">
          Subtotal <span className="figures text-ink">{formatMoney(breakdown.subtotal)}</span> · IVA{' '}
          <span className="figures text-ink">{formatMoney(breakdown.tax)}</span>
        </p>
      ) : null}
    </div>
  )
}
