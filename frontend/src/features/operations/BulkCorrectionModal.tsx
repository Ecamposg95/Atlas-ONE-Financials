/** R2·HU-04: la misma corrección a varios gastos.
 *
 *  Primero la vista previa (el servidor aplica todo y lo deshace), luego se
 *  aplica. Cada gasto se juzga con las reglas de la corrección individual:
 *  los que no pasan (mes cerrado, cancelado, IVA que no cuadra) se listan con
 *  su motivo y no detienen a los demás. */

import { useState } from 'react'
import { api, errorMessage } from '@/api/client'
import { Button } from '@/components/ui/Button'
import { SelectInput, TextInput } from '@/components/ui/Field'
import { Modal } from '@/components/ui/Modal'
import { formatDate, formatMoney } from '@/lib/format'
import { TREATMENT_LABELS } from '@/lib/taxes'
import type { TaxTreatment } from '@/types/api'

interface Option {
  id: string
  name: string
}

interface BulkItem {
  id: string
  date?: string
  description?: string
  amount?: string
  outcome: 'updated' | 'unchanged' | 'rejected'
  detail: string | null
}

interface BulkResult {
  dry_run: boolean
  updated: number
  unchanged: number
  rejected: number
  items: BulkItem[]
}

const KEEP = ''
const CLEAR = '__none__'

export function BulkCorrectionModal({
  open,
  ids,
  categories,
  vendors,
  projects,
  onClose,
  onApplied,
}: {
  open: boolean
  ids: string[]
  categories: Option[]
  vendors: Option[]
  projects: Option[]
  onClose: () => void
  onApplied: () => void
}) {
  const [form, setForm] = useState({ category_id: KEEP, tax_treatment: KEEP, vendor_id: KEEP, project_id: KEEP })
  const [reason, setReason] = useState('')
  const [preview, setPreview] = useState<BulkResult | null>(null)
  const [result, setResult] = useState<BulkResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function changes(): Record<string, string | null> {
    const out: Record<string, string | null> = {}
    for (const [field, value] of Object.entries(form)) {
      if (value === KEEP) continue
      out[field] = value === CLEAR ? null : value
    }
    return out
  }

  function reset() {
    setForm({ category_id: KEEP, tax_treatment: KEEP, vendor_id: KEEP, project_id: KEEP })
    setReason('')
    setPreview(null)
    setResult(null)
    setError(null)
  }

  function close() {
    if (busy) return
    const applied = result !== null
    reset()
    onClose()
    if (applied) onApplied()
  }

  async function run(dryRun: boolean) {
    setBusy(true)
    setError(null)
    try {
      const response = await api.post<BulkResult>(
        '/expenses/bulk-update',
        { ids, changes: changes(), reason: reason.trim(), dry_run: dryRun },
        { timeout: 120_000 },
      )
      if (dryRun) setPreview(response.data)
      else setResult(response.data)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const nothingChosen = Object.keys(changes()).length === 0
  const shown = result ?? preview
  const rejected = shown?.items.filter((item) => item.outcome === 'rejected') ?? []

  return (
    <Modal title={`Corregir ${ids.length} gasto${ids.length === 1 ? '' : 's'}`} open={open} onClose={close}>
      {result ? (
        <div className="space-y-4 text-sm">
          <Summary result={result} applied />
          <RejectedList items={rejected} />
          <div className="flex justify-end">
            <Button onClick={close}>Listo</Button>
          </div>
        </div>
      ) : (
        <form
          className="space-y-3"
          onSubmit={(event) => {
            event.preventDefault()
            void run(preview === null)
          }}
        >
          <p className="text-sm text-muted">
            Sólo se cambia lo que elijas; lo demás se queda igual. Monto, fecha y cuenta no se corrigen en
            lote. Cambiar la categoría de un gasto pagado registra su póliza de reclasificación.
          </p>
          <div className="grid gap-3 sm:grid-cols-2">
            <SelectInput
              label="Categoría"
              options={[{ value: KEEP, label: 'No cambiar' }, ...categories.map((c) => ({ value: c.id, label: c.name }))]}
              value={form.category_id}
              onChange={(event) => {
                setForm({ ...form, category_id: event.target.value })
                setPreview(null)
              }}
            />
            <SelectInput
              label="Tratamiento de IVA"
              options={[
                { value: KEEP, label: 'No cambiar' },
                ...(Object.keys(TREATMENT_LABELS) as TaxTreatment[])
                  .filter((treatment) => treatment !== 'TAXED')
                  .map((treatment) => ({ value: treatment, label: TREATMENT_LABELS[treatment] })),
              ]}
              value={form.tax_treatment}
              onChange={(event) => {
                setForm({ ...form, tax_treatment: event.target.value })
                setPreview(null)
              }}
            />
            <SelectInput
              label="Proveedor"
              options={[
                { value: KEEP, label: 'No cambiar' },
                { value: CLEAR, label: 'Sin proveedor' },
                ...vendors.map((v) => ({ value: v.id, label: v.name })),
              ]}
              value={form.vendor_id}
              onChange={(event) => {
                setForm({ ...form, vendor_id: event.target.value })
                setPreview(null)
              }}
            />
            {projects.length > 0 ? (
              <SelectInput
                label="Proyecto"
                options={[
                  { value: KEEP, label: 'No cambiar' },
                  { value: CLEAR, label: 'Sin proyecto' },
                  ...projects.map((p) => ({ value: p.id, label: p.name })),
                ]}
                value={form.project_id}
                onChange={(event) => {
                  setForm({ ...form, project_id: event.target.value })
                  setPreview(null)
                }}
              />
            ) : null}
          </div>
          <TextInput
            label="Motivo"
            hint="Queda en el historial de cada gasto."
            required
            minLength={3}
            maxLength={500}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
          />
          {preview ? (
            <div className="space-y-3 rounded-lg border border-border bg-surface-2/40 p-3 text-sm">
              <p className="font-medium">Vista previa: todavía no se cambió nada.</p>
              <Summary result={preview} applied={false} />
              <RejectedList items={rejected} />
            </div>
          ) : null}
          {error ? <p className="text-sm text-neg">{error}</p> : null}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={close} disabled={busy}>
              Cancelar
            </Button>
            {preview ? (
              <Button type="submit" disabled={busy || preview.updated === 0}>
                {busy ? 'Aplicando…' : `Aplicar a ${preview.updated}`}
              </Button>
            ) : (
              <Button type="submit" disabled={busy || nothingChosen}>
                {busy ? 'Revisando…' : 'Ver vista previa'}
              </Button>
            )}
          </div>
        </form>
      )}
    </Modal>
  )
}

function Summary({ result, applied }: { result: BulkResult; applied: boolean }) {
  return (
    <ul className="space-y-1">
      <li>
        <span className="figures font-medium">{result.updated}</span>{' '}
        {applied ? 'corregido' : 'se corregirían'}
        {applied && result.updated !== 1 ? 's' : ''}
      </li>
      {result.unchanged > 0 ? (
        <li className="text-muted">
          <span className="figures">{result.unchanged}</span> ya tenían esos datos
        </li>
      ) : null}
      {result.rejected > 0 ? (
        <li className="text-neg">
          <span className="figures">{result.rejected}</span> no se pueden corregir
        </li>
      ) : null}
    </ul>
  )
}

function RejectedList({ items }: { items: BulkItem[] }) {
  if (items.length === 0) return null
  return (
    <ul className="max-h-48 divide-y divide-border overflow-y-auto rounded-lg border border-border">
      {items.map((item) => (
        <li key={item.id} className="px-3 py-2 text-xs">
          <p className="font-medium text-ink">
            {item.description ?? 'Gasto'}
            {item.date ? <span className="font-normal text-muted"> · {formatDate(item.date)}</span> : null}
            {item.amount ? <span className="figures font-normal text-muted"> · {formatMoney(item.amount)}</span> : null}
          </p>
          <p className="text-neg">{item.detail}</p>
        </li>
      ))}
    </ul>
  )
}
