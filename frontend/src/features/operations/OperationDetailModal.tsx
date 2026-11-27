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
import { formatDate } from '@/lib/format'
import type { CfdiOperationFields, Contact } from '@/types/api'

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
}

type Tab = 'detail' | 'history'

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
    })
    setCfdi(cfdiFrom(operation))
  }, [operation])

  const saveMutation = useMutation({
    mutationFn: async () => {
      if (!operation) return
      // Sólo lo que cambió: el historial registra exactamente lo que se tocó.
      const payload: Record<string, unknown> = customers ? cfdiChanges(cfdi, operation) : {}
      if (operation.status === 'PAID' && paidCorrections) {
        if (form.category_id !== operation.category_id) payload.category_id = form.category_id
        if (form.notes !== (operation.notes ?? '')) payload.notes = form.notes || null
        if (Object.keys(payload).length === 0) return
        await api.patch(`${endpoint}/${operation.id}`, { ...payload, reason: reason.trim() })
        setReason('')
        return
      }
      if (operation.status !== 'PENDING') {
        // Cobrado o cancelado: sólo los datos para la factura, que no tocan el libro.
        if (Object.keys(payload).length > 0) await api.patch(`${endpoint}/${operation.id}`, payload)
        return
      }
      if (form.date !== operation.date) payload.date = form.date
      if (form.description.trim() !== operation.description) payload.description = form.description.trim()
      if (Number(form.amount) !== Number(operation.amount)) payload.amount = form.amount
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
