/** Detalle de un ingreso o gasto: corregirlo mientras está pendiente y ver su historial.
 *
 *  Pendiente no tiene movimiento ni póliza, así que se puede corregir. De un gasto
 *  pagado (R2·HU-02) se corrigen categoría y notas con motivo, mientras el mes
 *  esté abierto; monto, fecha y cuenta exigen cancelar (reverso) y volver a registrar.
 *  Cada cambio queda en el historial con su valor anterior (HU-09).
 */

import { useEffect, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { api, errorMessage } from '@/api/client'
import { Button } from '@/components/ui/Button'
import { HistoryTimeline } from '@/components/ui/HistoryTimeline'
import { SelectInput, TextInput } from '@/components/ui/Field'
import { Modal } from '@/components/ui/Modal'
import { Money } from '@/components/ui/Money'
import { Segmented } from '@/components/ui/Segmented'
import { StatusBadge } from '@/components/ui/StatusBadge'
import { CfdiFields, EMPTY_CFDI, cfdiChanges, cfdiFrom } from '@/features/fiscal/CfdiOperationFields'
import { formatDate, formatMoney } from '@/lib/format'
import { TaxSelect } from '@/components/ui/TaxSelect'
import { TREATMENT_LABELS, defaultTreatment } from '@/lib/taxes'
import type { CfdiOperationFields, Contact, TaxTreatment } from '@/types/api'

interface Operation extends CfdiOperationFields {
  id: string
  date: string
  description: string
  amount: string
  category_id: string
  financial_account_id: string | null
  status: string
  notes: string | null
  customer_id?: string | null
  subtotal?: string
  tax_rate?: string
  tax_amount?: string
  tax_treatment?: TaxTreatment
  retention_isr?: string
  retention_iva?: string
}

const UNTAXED_OPTIONS = (['UNCLASSIFIED', 'ZERO_RATED', 'EXEMPT', 'NOT_OBJECT'] as TaxTreatment[]).map((value) => ({
  value,
  label: TREATMENT_LABELS[value],
}))

type Tab = 'detail' | 'history'

function formatRate(rate: string | undefined): string {
  return `${(Number(rate ?? 0) * 100).toLocaleString('es-MX', { maximumFractionDigits: 2 })}%`
}

export function OperationDetailModal({
  operation,
  canWrite,
  endpoint,
  paidLabel,
  accountLabel,
  categories,
  accounts,
  categoryName,
  accountName,
  onClose,
  onSaved,
  customers,
  paidCorrections = false,
}: {
  operation: Operation | null
  /** Captura en adelante: Consulta sólo ve (el API rechaza sus cambios). */
  canWrite: boolean
  endpoint: string
  paidLabel: string
  accountLabel: string
  categories: { id: string; name: string }[]
  accounts: { id: string; name: string; active: boolean }[]
  categoryName: (id: string) => string
  accountName: (id: string | null) => string
  onClose: () => void
  onSaved: () => void
  /** Sólo ingresos: con los clientes se muestran los datos para la factura. */
  customers?: Contact[]
  /** Sólo gastos: lo pagado admite corregir categoría y notas con motivo. */
  paidCorrections?: boolean
}) {
  const [tab, setTab] = useState<Tab>('detail')
  const [error, setError] = useState<string | null>(null)
  const [form, setForm] = useState({
    date: '',
    description: '',
    amount: '',
    category_id: '',
    financial_account_id: '',
    notes: '',
    tax_rate: '0',
    tax_treatment: 'UNCLASSIFIED' as TaxTreatment,
  })
  const [reason, setReason] = useState('')
  const [cfdi, setCfdi] = useState(EMPTY_CFDI)

  // Abrir otra operación vuelve a la pestaña de detalle; recargar la misma no.
  useEffect(() => {
    setTab('detail')
    setError(null)
    setReason('')
  }, [operation?.id])

  useEffect(() => {
    if (!operation) return
    setForm({
      date: operation.date,
      description: operation.description,
      amount: operation.amount,
      category_id: operation.category_id,
      financial_account_id: operation.financial_account_id ?? '',
      notes: operation.notes ?? '',
      tax_rate: operation.tax_rate ?? '0',
      tax_treatment: operation.tax_treatment ?? defaultTreatment(operation.tax_rate ?? '0'),
    })
    setCfdi(cfdiFrom(operation))
  }, [operation])

  const saveMutation = useMutation({
    mutationFn: async () => {
      if (!operation) return
      // Sólo lo que cambió: el historial registra exactamente lo que se tocó.
      const payload: Record<string, unknown> = customers ? cfdiChanges(cfdi, operation) : {}
      const treatmentChanged = operation.tax_treatment !== undefined && form.tax_treatment !== operation.tax_treatment
      if (operation.status === 'PAID' && paidCorrections) {
        if (form.category_id !== operation.category_id) payload.category_id = form.category_id
        if (treatmentChanged) payload.tax_treatment = form.tax_treatment
        if (form.notes !== (operation.notes ?? '')) payload.notes = form.notes || null
        if (Object.keys(payload).length === 0) return
        await api.patch(`${endpoint}/${operation.id}`, { ...payload, reason: reason.trim() })
        setReason('')
        return
      }
      if (operation.status !== 'PENDING') {
        // Cobrado o cancelado: sólo los datos para la factura y el tratamiento
        // de IVA sin tasa, que no tocan el libro.
        if (treatmentChanged) payload.tax_treatment = form.tax_treatment
        if (Object.keys(payload).length > 0) await api.patch(`${endpoint}/${operation.id}`, payload)
        return
      }
      if (form.date !== operation.date) payload.date = form.date
      if (form.description.trim() !== operation.description) payload.description = form.description.trim()
      if (Number(form.amount) !== Number(operation.amount)) payload.amount = form.amount
      if (Number(form.tax_rate) !== Number(operation.tax_rate ?? 0)) payload.tax_rate = form.tax_rate
      if (treatmentChanged) payload.tax_treatment = form.tax_treatment
      if (form.category_id !== operation.category_id) payload.category_id = form.category_id
      if (form.financial_account_id !== (operation.financial_account_id ?? ''))
        payload.financial_account_id = form.financial_account_id || null
      if (form.notes !== (operation.notes ?? '')) payload.notes = form.notes || null
      if (Object.keys(payload).length === 0) return
      await api.patch(`${endpoint}/${operation.id}`, payload)
    },
    onSuccess: () => {
      setError(null)
      onSaved()
      setTab('history')
    },
    onError: (err) => setError(errorMessage(err)),
  })

  if (!operation) return null
  const editable = operation.status === 'PENDING' && canWrite
  const correctable = operation.status === 'PAID' && paidCorrections && canWrite
  const customer = customers?.find((item) => item.id === operation.customer_id)

  return (
    <Modal title={operation.description} open onClose={onClose}>
      <div className="mb-4 flex items-center justify-between gap-3">
        <Segmented<Tab>
          size="sm"
          options={[
            { key: 'detail', label: 'Detalle' },
            { key: 'history', label: 'Historial' },
          ]}
          value={tab}
          onChange={setTab}
        />
        <StatusBadge status={operation.status} paidLabel={paidLabel} />
      </div>

      {tab === 'history' ? (
        <div className="max-h-[60vh] overflow-y-auto pr-1">
          <HistoryTimeline endpoint={endpoint} entityId={operation.id} />
        </div>
      ) : editable ? (
        <form
          className="space-y-3"
          onSubmit={(event) => {
            event.preventDefault()
            saveMutation.mutate()
          }}
        >
          <TextInput
            label="Concepto"
            required
            value={form.description}
            onChange={(event) => setForm({ ...form, description: event.target.value })}
          />
          <div className="grid grid-cols-2 gap-3">
            <TextInput
              label="Monto total"
              required
              inputMode="decimal"
              value={form.amount}
              onChange={(event) => setForm({ ...form, amount: event.target.value })}
            />
            <TextInput
              label="Fecha"
              type="date"
              required
              value={form.date}
              onChange={(event) => setForm({ ...form, date: event.target.value })}
            />
          </div>
          {operation.tax_rate !== undefined ? (
            <TaxSelect
              total={form.amount}
              rate={form.tax_rate}
              treatment={form.tax_treatment}
              onRateChange={(rate) => setForm({ ...form, tax_rate: rate })}
              onTaxChange={(rate, treatment) => setForm({ ...form, tax_rate: rate, tax_treatment: treatment })}
            />
          ) : null}
          <SelectInput
            label="Categoría"
            required
            options={categories.map((category) => ({ value: category.id, label: category.name }))}
            value={form.category_id}
            onChange={(event) => setForm({ ...form, category_id: event.target.value })}
          />
          <SelectInput
            label={`${accountLabel} (opcional)`}
            placeholder="Todavía no lo sé"
            options={accounts
              .filter((account) => account.active || account.id === form.financial_account_id)
              .map((account) => ({ value: account.id, label: account.name }))}
            value={form.financial_account_id}
            onChange={(event) => setForm({ ...form, financial_account_id: event.target.value })}
          />
          <TextInput
            label="Notas (opcional)"
            value={form.notes}
            onChange={(event) => setForm({ ...form, notes: event.target.value })}
          />
          {customers ? (
            <CfdiFields
              title="Datos para la factura (opcional)"
              value={cfdi}
              onChange={setCfdi}
              customer={customer}
            />
          ) : null}
          <p className="text-xs text-muted">
            Cada cambio queda en el historial con su valor anterior.
          </p>
          {error ? <p className="text-sm text-neg">{error}</p> : null}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={onClose}>
              Cerrar
            </Button>
            <Button type="submit" disabled={saveMutation.isPending}>
              {saveMutation.isPending ? 'Guardando…' : 'Guardar cambios'}
            </Button>
          </div>
        </form>
      ) : (
        <div className="space-y-3 text-sm">
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2">
            <dt className="text-muted">Monto</dt>
            <dd>
              <Money value={operation.amount} tone="ink" />
            </dd>
            {operation.tax_rate !== undefined ? (
              <>
                <dt className="text-muted">Desglose</dt>
                <dd className="figures">
                  Base {formatMoney(operation.subtotal ?? operation.amount)}
                  {Number(operation.tax_amount ?? 0) > 0
                    ? ` · IVA ${formatRate(operation.tax_rate)} ${formatMoney(operation.tax_amount ?? 0)}`
                    : ''}
                </dd>
                <dt className="text-muted">IVA</dt>
                <dd>
                  {operation.tax_treatment ? TREATMENT_LABELS[operation.tax_treatment] : '—'}
                  {operation.tax_treatment === 'UNCLASSIFIED' ? (
                    <span className="ml-1 text-xs text-warn">pendiente de revisar</span>
                  ) : null}
                </dd>
              </>
            ) : null}
            {Number(operation.retention_isr ?? 0) + Number(operation.retention_iva ?? 0) > 0 ? (
              <>
                <dt className="text-muted">Retenciones</dt>
                <dd className="figures">
                  ISR {formatMoney(operation.retention_isr ?? 0)} · IVA {formatMoney(operation.retention_iva ?? 0)}
                </dd>
              </>
            ) : null}
            <dt className="text-muted">Fecha</dt>
            <dd>{formatDate(operation.date)}</dd>
            <dt className="text-muted">Categoría</dt>
            <dd>{categoryName(operation.category_id)}</dd>
            <dt className="text-muted">Cuenta</dt>
            <dd>{accountName(operation.financial_account_id)}</dd>
            {operation.notes ? (
              <>
                <dt className="text-muted">Notas</dt>
                <dd>{operation.notes}</dd>
              </>
            ) : null}
          </dl>
          <p className="text-xs text-muted">
            {!canWrite
              ? 'Tu permiso es de consulta: puedes verla, no modificarla.'
              : operation.status === 'CANCELLED'
                ? 'Está cancelada: ya no se puede modificar.'
                : correctable
                  ? 'Ya movió dinero: monto, fecha y cuenta sólo se corrigen cancelándolo (se registra un reverso) y registrándolo de nuevo. Categoría y notas se corrigen aquí.'
                  : 'Ya movió dinero: para corregirla, cancélala con el botón Cancelar de la lista (se registra un reverso que deshace el movimiento de dinero) y regístrala de nuevo. Así la contabilidad conserva el rastro.'}
          </p>
          {correctable ? (
            <form
              className="space-y-3 border-t border-border pt-4"
              onSubmit={(event) => {
                event.preventDefault()
                saveMutation.mutate()
              }}
            >
              <div>
                <h3 className="text-sm font-semibold">Corregir</h3>
                <p className="text-xs text-muted">
                  Cambiar la categoría registra una póliza de reclasificación en la fecha del gasto; el
                  dinero y el IVA no se mueven. Si el mes ya está cerrado, hay que reabrirlo.
                </p>
              </div>
              <SelectInput
                label="Categoría"
                required
                options={categories.map((category) => ({ value: category.id, label: category.name }))}
                value={form.category_id}
                onChange={(event) => setForm({ ...form, category_id: event.target.value })}
              />
              {Number(operation.tax_rate ?? 0) === 0 && operation.tax_treatment ? (
                <SelectInput
                  label="Tratamiento de IVA"
                  hint="Sin IVA puede ser tasa 0, exento o no objeto; lo confirma contabilidad."
                  options={UNTAXED_OPTIONS}
                  value={form.tax_treatment}
                  onChange={(event) => setForm({ ...form, tax_treatment: event.target.value as TaxTreatment })}
                />
              ) : null}
              <TextInput
                label="Notas (opcional)"
                value={form.notes}
                onChange={(event) => setForm({ ...form, notes: event.target.value })}
              />
              <TextInput
                label="Motivo de la corrección"
                hint="Queda en el historial con el valor anterior."
                required
                minLength={3}
                maxLength={500}
                value={reason}
                onChange={(event) => setReason(event.target.value)}
              />
              {error ? <p className="text-sm text-neg">{error}</p> : null}
              <div className="flex justify-end">
                <Button type="submit" disabled={saveMutation.isPending}>
                  {saveMutation.isPending ? 'Guardando…' : 'Guardar corrección'}
                </Button>
              </div>
            </form>
          ) : null}
          {customers && canWrite ? (
            <form
              className="space-y-3 border-t border-border pt-4"
              onSubmit={(event) => {
                event.preventDefault()
                saveMutation.mutate()
              }}
            >
              <div>
                <h3 className="text-sm font-semibold">Datos para la factura</h3>
                <p className="text-xs text-muted">Se pueden corregir siempre: no cambian tus números.</p>
              </div>
              <CfdiFields collapsible={false} value={cfdi} onChange={setCfdi} customer={customer} />
              {Number(operation.tax_rate ?? 0) === 0 && operation.tax_treatment ? (
                <SelectInput
                  label="Tratamiento de IVA"
                  hint="Sin IVA puede ser tasa 0, exento o no objeto; lo confirma contabilidad."
                  options={UNTAXED_OPTIONS}
                  value={form.tax_treatment}
                  onChange={(event) => setForm({ ...form, tax_treatment: event.target.value as TaxTreatment })}
                />
              ) : null}
              {error ? <p className="text-sm text-neg">{error}</p> : null}
              <div className="flex justify-end">
                <Button type="submit" disabled={saveMutation.isPending}>
                  {saveMutation.isPending ? 'Guardando…' : 'Guardar datos de factura'}
                </Button>
              </div>
            </form>
          ) : null}
        </div>
      )}
    </Modal>
  )
}
