/** Uso de CFDI, método y forma de pago de un ingreso o cuenta por cobrar.
 *
 *  Opcionales y plegados: quien no factura no los ve. Las opciones vienen del
 *  catálogo del SAT (el uso, filtrado por el régimen del cliente) y la
 *  coherencia entre ellas la decide el backend: la UI muestra su mensaje. */

import { useState } from 'react'
import { SelectInput } from '@/components/ui/Field'
import { asOptions, useSatCatalog } from '@/features/fiscal/FiscalFields'
import type { CfdiOperationFields as CfdiValues, Contact } from '@/types/api'

export interface CfdiForm {
  cfdi_use: string
  cfdi_payment_method: string
  cfdi_payment_form: string
}

export const EMPTY_CFDI: CfdiForm = { cfdi_use: '', cfdi_payment_method: '', cfdi_payment_form: '' }

const CFDI_KEYS = ['cfdi_use', 'cfdi_payment_method', 'cfdi_payment_form'] as const

export function cfdiFrom(values: CfdiValues): CfdiForm {
  return {
    cfdi_use: values.cfdi_use ?? '',
    cfdi_payment_method: values.cfdi_payment_method ?? '',
    cfdi_payment_form: values.cfdi_payment_form ?? '',
  }
}

/** Para dar de alta: sólo lo capturado. */
export function cfdiCreatePayload(form: CfdiForm): Partial<CfdiForm> {
  return Object.fromEntries(CFDI_KEYS.filter((key) => form[key]).map((key) => [key, form[key]]))
}

/** Para editar: sólo lo que cambió; lo vacío viaja como null para poder borrarlo. */
export function cfdiChanges(form: CfdiForm, saved: CfdiValues): Record<string, string | null> {
  const before = cfdiFrom(saved)
  return Object.fromEntries(
    CFDI_KEYS.filter((key) => form[key] !== before[key]).map((key) => [key, form[key] || null]),
  )
}

/**
 * Al cambiar de cliente se precarga su uso de CFDI por defecto, salvo que la
 * persona ya haya elegido otro a mano.
 */
export function withCustomerDefault(form: CfdiForm, previous: Contact | undefined, next: Contact | undefined): CfdiForm {
  const untouched = !form.cfdi_use || form.cfdi_use === (previous?.default_cfdi_use ?? '')
  return untouched ? { ...form, cfdi_use: next?.default_cfdi_use ?? '' } : form
}

function summary(form: CfdiForm): string | null {
  const parts = [
    form.cfdi_use ? `Uso ${form.cfdi_use}` : null,
    form.cfdi_payment_method || null,
    form.cfdi_payment_form ? `Forma ${form.cfdi_payment_form}` : null,
  ].filter(Boolean)
  return parts.length > 0 ? parts.join(' · ') : null
}

export function CfdiFields({
  value,
  onChange,
  customer,
  title = '¿Vas a facturarla?',
  collapsible = true,
}: {
  value: CfdiForm
  onChange: (value: CfdiForm) => void
  /** Cliente de la operación: su RFC y régimen filtran los usos de CFDI. */
  customer?: Contact
  title?: string
  /** En un formulario de alta va plegado; en una ficha se muestra abierto. */
  collapsible?: boolean
}) {
  const [open, setOpen] = useState(() => !collapsible || summary(value) !== null)
  const regimen = customer?.fiscal_regime ?? ''
  const rfc = customer?.tax_id ?? ''
  const uses = useSatCatalog('c_UsoCFDI', { ...(rfc ? { rfc } : {}), ...(regimen ? { regimen } : {}) })
  const methods = useSatCatalog('c_MetodoPago')
  const forms = useSatCatalog('c_FormaPago')
  const current = summary(value)

  const useHint = !customer
    ? undefined
    : regimen
      ? `Sólo los usos que aplican al régimen ${regimen} del cliente.`
      : 'Captura el régimen del cliente en su ficha para ver sólo los usos que le aplican.'

  const fields = (
    <div className="space-y-3">
      <SelectInput
        label="Uso de CFDI (opcional)"
        placeholder={uses.isLoading ? 'Cargando…' : 'Sin capturar'}
        options={asOptions(uses.data, value.cfdi_use)}
        value={value.cfdi_use}
        hint={
          customer?.default_cfdi_use && value.cfdi_use === customer.default_cfdi_use
            ? 'Es el que usa este cliente por defecto.'
            : useHint
        }
        onChange={(event) => onChange({ ...value, cfdi_use: event.target.value })}
      />
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <SelectInput
          label="Método de pago (opcional)"
          placeholder={methods.isLoading ? 'Cargando…' : 'Sin capturar'}
          options={asOptions(methods.data, value.cfdi_payment_method)}
          value={value.cfdi_payment_method}
          hint="PUE si te pagan de una vez; PPD si te pagan después o en partes."
          onChange={(event) => onChange({ ...value, cfdi_payment_method: event.target.value })}
        />
        <SelectInput
          label="Forma de pago (opcional)"
          placeholder={forms.isLoading ? 'Cargando…' : 'Sin capturar'}
          options={asOptions(forms.data, value.cfdi_payment_form)}
          value={value.cfdi_payment_form}
          hint={value.cfdi_payment_method === 'PPD' ? 'Con PPD va 99 (Por definir).' : 'Cómo te pagaron.'}
          onChange={(event) => onChange({ ...value, cfdi_payment_form: event.target.value })}
        />
      </div>
    </div>
  )

  if (!collapsible) return fields

  return (
    <details
      className="rounded-lg border border-border bg-surface-2/40 px-3 py-2"
      open={open}
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary className="cursor-pointer text-sm text-muted">
        {title}
        {current ? <span className="figures ml-2 text-xs text-ink">{current}</span> : null}
      </summary>
      <p className="mb-3 mt-2 text-xs text-muted">
        Datos del SAT para la factura. Si no facturas, déjalos vacíos: no cambian tus números.
      </p>
      {fields}
    </details>
  )
}
