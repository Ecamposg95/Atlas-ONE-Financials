/** Desglose de IVA para la vista previa del formulario.
 *
 *  Espeja la fórmula del servidor (app/services/taxes.py), que es la autoridad:
 *  el impuesto se obtiene por diferencia para que subtotal + IVA == total exacto.
 *  Se trabaja en centavos enteros para no arrastrar errores de punto flotante.
 */

import type { TaxTreatment } from '@/types/api'

export const TAX_RATES = [
  { value: '0.16', label: 'IVA 16%' },
  { value: '0.08', label: 'IVA 8% (frontera)' },
  { value: '0', label: 'Sin IVA / exento' },
]

/** R2·HU-05: sin IVA no es una sola cosa. Tasa 0, exento y no objeto se
 *  declaran distinto; "sin clasificar" lo deja pendiente para contabilidad. */
export const TREATMENT_LABELS: Record<TaxTreatment, string> = {
  TAXED: 'Gravado',
  ZERO_RATED: 'Tasa 0%',
  EXEMPT: 'Exento',
  NOT_OBJECT: 'No objeto de IVA',
  UNCLASSIFIED: 'Sin clasificar',
}

/** Opciones del selector: tasa y tratamiento juntos, "0.16|TAXED". */
export const TAX_OPTIONS = [
  { value: '0.16|TAXED', label: 'IVA 16%' },
  { value: '0.08|TAXED', label: 'IVA 8% (frontera)' },
  { value: '0|ZERO_RATED', label: 'Tasa 0%' },
  { value: '0|EXEMPT', label: 'Exento' },
  { value: '0|NOT_OBJECT', label: 'No objeto de IVA' },
  { value: '0|UNCLASSIFIED', label: 'Sin IVA, sin clasificar (lo revisa contabilidad)' },
]

export function defaultTreatment(rate: string): TaxTreatment {
  return Number(rate) > 0 ? 'TAXED' : 'UNCLASSIFIED'
}

/** Retenciones frecuentes, sobre la base sin IVA. Contabilidad confirma cuál aplica. */
export const ISR_RETENTION_RATES = [
  { value: '0.10', label: 'ISR 10% (honorarios o arrendamiento de persona física)' },
  { value: '0.0125', label: 'ISR 1.25% (persona física en RESICO)' },
]
export const IVA_RETENTION_RATES = [
  { value: '0.106667', label: 'IVA 2/3 (10.67%: honorarios o arrendamiento)' },
  { value: '0.04', label: 'IVA 4% (fletes)' },
  { value: '0.06', label: 'IVA 6% (servicios con personal)' },
]

export interface TaxBreakdown {
  total: number
  subtotal: number
  tax: number
}

export function splitTotal(total: string | number, rate: string | number): TaxBreakdown {
  const totalCents = Math.round(Number(total || 0) * 100)
  const taxRate = Number(rate || 0)
  if (!Number.isFinite(totalCents) || totalCents <= 0 || taxRate <= 0) {
    const value = Number.isFinite(totalCents) ? totalCents / 100 : 0
    return { total: value, subtotal: value, tax: 0 }
  }
  const subtotalCents = Math.round(totalCents / (1 + taxRate))
  return {
    total: totalCents / 100,
    subtotal: subtotalCents / 100,
    tax: (totalCents - subtotalCents) / 100,
  }
}
