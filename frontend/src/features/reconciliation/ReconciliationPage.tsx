import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api, errorMessage } from '@/api/client'
import { Button } from '@/components/ui/Button'
import { EmptyState } from '@/components/ui/EmptyState'
import { SelectInput, TextInput } from '@/components/ui/Field'
import { Modal } from '@/components/ui/Modal'
import { Money } from '@/components/ui/Money'
import { PageHeader } from '@/components/ui/PageHeader'
import { Card, Table } from '@/components/ui/Table'
import { useActiveRole } from '@/lib/companies'
import { formatDate, formatMoney } from '@/lib/format'
import { useAccounts } from '@/lib/hooks'
import type {
  BankLine,
  BankStatement,
  BankStatementDetail,
  BankStatementPreview,
  BankTransactionBrief,
  Page,
} from '@/types/api'

const RECONCILABLE = ['BANK', 'PROCESSOR', 'OTHER']
const ADMIN_ROLES = ['OWNER', 'ADMIN']
const WRITE_ROLES = ['OWNER', 'ADMIN', 'ACCOUNTANT', 'MEMBER']

const FIELD_LABELS: Record<string, string> = {
  date: 'Fecha',
  description: 'Concepto',
  reference: 'Referencia',
  amount: 'Importe con signo',
  deposit: 'Abonos',
  withdrawal: 'Cargos',
}

const STATUS: Record<string, { label: string; className: string }> = {
  OPEN: { label: 'En proceso', className: 'bg-warn/10 text-warn' },
  CLOSED: { label: 'Cerrada', className: 'bg-pos/10 text-pos' },
  CANCELLED: { label: 'Cancelada', className: 'bg-muted/10 text-muted' },
}

const LINE_STATUS: Record<string, { label: string; className: string }> = {
  PENDING: { label: 'Pendiente', className: 'bg-warn/10 text-warn' },
  MATCHED: { label: 'Conciliado', className: 'bg-pos/10 text-pos' },
  IGNORED: { label: 'No corresponde', className: 'bg-muted/10 text-muted' },
}

function Pill({ config }: { config: { label: string; className: string } }) {
  return (
    <span className={`inline-flex whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ${config.className}`}>
      {config.label}
    </span>
  )
}

function Signed({ value }: { value: string | number }) {
  return <Money value={value} size="sm" tone={Number(value) < 0 ? 'neg' : 'ink'} />
}

/** Conciliación bancaria: lista de estados de cuenta y, al abrir uno, sus renglones. */
export function ReconciliationPage() {
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  const role = useActiveRole()
  const canWrite = WRITE_ROLES.includes(role ?? '')
  const { data: accounts, isLoading: accountsLoading } = useAccounts()
  const bankAccounts = (accounts ?? []).filter((a) => RECONCILABLE.includes(a.type) && a.active)

  const { data: statements, isLoading } = useQuery({
    queryKey: ['bank-statements', 'list'],
    queryFn: async () => (await api.get<Page<BankStatement>>('/bank-statements', { params: { limit: 100 } })).data,
  })

  if (selectedId) {
    return <StatementView id={selectedId} canWrite={canWrite} onBack={() => setSelectedId(null)} />
  }

  return (
    <div>
      <PageHeader
        title="Conciliación"
        description="Compara el estado de cuenta del banco con lo que tienes registrado. Conciliar no mueve ningún saldo."
        actions={
          canWrite && bankAccounts.length > 0 ? (
            <Button onClick={() => setUploading(true)}>Subir estado de cuenta</Button>
          ) : null
        }
      />

      {isLoading || accountsLoading ? (
        <div className="h-48 animate-pulse rounded-xl bg-surface-2" />
      ) : bankAccounts.length === 0 ? (
        <EmptyState
          title="Sin cuentas de banco"
          message="Da de alta la cuenta de banco o el procesador de pagos que quieres conciliar."
          action={
            <Link to="/cuentas?nueva=1">
              <Button>Agregar cuenta</Button>
            </Link>
          }
        />
      ) : (statements?.items.length ?? 0) === 0 ? (
        <EmptyState
          title="Aún no has conciliado nada"
          message="Descarga el estado de cuenta de tu banco en Excel o CSV y súbelo aquí. Te propondremos qué renglón corresponde a qué movimiento."
          action={canWrite ? <Button onClick={() => setUploading(true)}>Subir estado de cuenta</Button> : undefined}
        />
      ) : (
        <Table headers={['Cuenta', 'Periodo', 'Renglones', 'Pendientes', 'Con diferencia', 'Estado', '']} secondary={[3, 5]}>
          {statements!.items.map((statement) => (
            <tr
              key={statement.id}
              className="cursor-pointer hover:bg-surface-2"
              onClick={() => setSelectedId(statement.id)}
            >
              <td className="px-4 py-3">
                <div className="font-medium">{statement.account_name ?? 'Cuenta'}</div>
                <div className="max-w-[220px] truncate text-xs text-muted">{statement.filename}</div>
              </td>
              <td className="whitespace-nowrap px-4 py-3 text-ink-soft">
                {formatDate(statement.period_start)} – {formatDate(statement.period_end)}
              </td>
              <td className="figures px-4 py-3">{statement.lines_count}</td>
              <td className={`figures px-4 py-3 ${statement.pending_count ? 'font-medium text-warn' : 'text-muted'}`}>
                {statement.pending_count}
              </td>
              <td className={`figures px-4 py-3 ${statement.differences_count ? 'font-medium text-neg' : 'text-muted'}`}>
                {statement.differences_count}
              </td>
              <td className="px-4 py-3">
                <Pill config={STATUS[statement.status] ?? STATUS.OPEN} />
              </td>
              <td className="px-4 py-3 text-right text-xs text-accent">Abrir</td>
            </tr>
          ))}
        </Table>
      )}

      {uploading ? (
        <UploadModal
          accounts={bankAccounts.map((a) => ({ value: a.id, label: a.name }))}
          onClose={() => setUploading(false)}
          onCreated={(id) => {
            setUploading(false)
            setSelectedId(id)
          }}
        />
      ) : null}
    </div>
  )
}

function UploadModal({
  accounts,
  onClose,
  onCreated,
}: {
  accounts: { value: string; label: string }[]
  onClose: () => void
  onCreated: (id: string) => void
}) {
  const queryClient = useQueryClient()
  const [accountId, setAccountId] = useState(accounts[0]?.value ?? '')
  const [file, setFile] = useState<File | null>(null)
  const [mapping, setMapping] = useState<Record<string, string>>({})
  const [closingBalance, setClosingBalance] = useState('')
  const [preview, setPreview] = useState<BankStatementPreview | null>(null)
  const [error, setError] = useState<string | null>(null)

  function form(chosen: File, map: Record<string, string>) {
    const data = new FormData()
    data.append('file', chosen)
    if (Object.keys(map).length) data.append('mapping', JSON.stringify(map))
    return data
  }

  const previewMutation = useMutation({
    mutationFn: async ({ chosen, map }: { chosen: File; map: Record<string, string> }) =>
      (await api.post<BankStatementPreview>('/bank-statements/preview', form(chosen, map), { timeout: 120000 })).data,
    onSuccess: (data) => {
      setPreview(data)
      setMapping(data.mapping)
      setError(null)
    },
    onError: (err) => {
      setPreview(null)
      setError(errorMessage(err))
    },
  })

  const createMutation = useMutation({
    mutationFn: async () => {
      const data = form(file!, mapping)
      data.append('financial_account_id', accountId)
      if (closingBalance.trim()) data.append('closing_balance', closingBalance.trim())
      return (await api.post<BankStatementDetail>('/bank-statements', data, { timeout: 120000 })).data
    },
    onSuccess: (detail) => {
      void queryClient.invalidateQueries({ queryKey: ['bank-statements'] })
      onCreated(detail.statement.id)
    },
    onError: (err) => setError(errorMessage(err)),
  })

  function changeMapping(field: string, column: string) {
    if (!file) return
    const next = { ...mapping }
    if (column) next[field] = column
    else delete next[field]
    setMapping(next)
    // Mandar el campo vacío le dice al servidor que no use la columna detectada.
    previewMutation.mutate({ chosen: file, map: { ...next, ...(column ? {} : { [field]: '' }) } })
  }

  const columnOptions = (preview?.columns ?? []).map((c) => ({ value: c, label: c }))
  const ready = Boolean(file && preview && !preview.problem && preview.total_rows > 0 && accountId)

  return (
    <Modal title="Subir estado de cuenta" open onClose={onClose} size="lg">
      <h2 className="font-display text-lg font-semibold tracking-tight">Subir estado de cuenta</h2>
      <p className="mt-1 text-sm text-muted">
        Excel (.xlsx) o CSV, como lo descargas de tu banca en línea. Primero verás cómo se lee; nada se guarda hasta que
        confirmes.
      </p>

      <div className="mt-5 grid gap-4 sm:grid-cols-2">
        <SelectInput label="Cuenta" options={accounts} value={accountId} onChange={(e) => setAccountId(e.target.value)} />
        <TextInput
          label="Saldo final del estado de cuenta (opcional)"
          inputMode="decimal"
          placeholder="0.00"
          value={closingBalance}
          onChange={(e) => setClosingBalance(e.target.value)}
          hint="Lo puedes capturar después. Sin él no se comparan saldos."
        />
      </div>

      <div className="mt-4">
        <input
          type="file"
          accept=".csv,.xlsx,.xlsm,text/csv"
          aria-label="Archivo del estado de cuenta"
          className="block w-full text-sm text-ink-soft file:mr-3 file:rounded file:border file:border-border file:bg-surface file:px-3.5 file:py-2 file:text-sm file:font-medium file:text-ink hover:file:bg-surface-2"
          onChange={(event) => {
            const chosen = event.target.files?.[0] ?? null
            setFile(chosen)
            setPreview(null)
            setMapping({})
            if (chosen) previewMutation.mutate({ chosen, map: {} })
          }}
        />
      </div>

      {error ? <p className="mt-3 rounded bg-neg/10 px-3 py-2 text-sm text-neg">{error}</p> : null}
      {previewMutation.isPending ? <div className="mt-4 h-24 animate-pulse rounded bg-surface-2" /> : null}

      {preview ? (
        <div className="mt-5">
          <h3 className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted">Columnas</h3>
          <div className="mt-2 grid gap-3 sm:grid-cols-3">
            {Object.keys(FIELD_LABELS).map((field) => (
              <SelectInput
                key={field}
                label={FIELD_LABELS[field]}
                options={columnOptions}
                placeholder="No usar"
                value={mapping[field] ?? ''}
                onChange={(e) => changeMapping(field, e.target.value)}
              />
            ))}
          </div>

          {preview.problem ? (
            <p className="mt-3 rounded bg-warn/10 px-3 py-2 text-sm text-warn">{preview.problem}</p>
          ) : (
            <>
              <p className="mt-4 text-sm text-ink-soft">
                {preview.total_rows} renglones
                {preview.period_start && preview.period_end
                  ? `, del ${formatDate(preview.period_start)} al ${formatDate(preview.period_end)}`
                  : ''}
                . Abonos {formatMoney(preview.deposits)}, cargos {formatMoney(preview.withdrawals)}.
                {preview.skipped_count
                  ? ` Se omiten ${preview.skipped_count} renglones sin fecha o sin importe (encabezados, totales).`
                  : ''}
              </p>
              <div className="mt-3 max-h-56 overflow-auto rounded border border-border">
                <table className="w-full text-xs">
                  <tbody className="divide-y divide-border">
                    {preview.rows.map((row) => (
                      <tr key={row.row_number}>
                        <td className="whitespace-nowrap px-3 py-1.5 text-muted">{formatDate(row.date)}</td>
                        <td className="px-3 py-1.5">{row.description}</td>
                        <td className="px-3 py-1.5 text-muted">{row.reference ?? ''}</td>
                        <td className="px-3 py-1.5 text-right">
                          <Signed value={row.amount} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      ) : null}

      <div className="mt-6 flex justify-end gap-2">
        <Button variant="ghost" onClick={onClose}>
          Cancelar
        </Button>
        <Button disabled={!ready || createMutation.isPending} onClick={() => createMutation.mutate()}>
          {createMutation.isPending ? 'Importando…' : 'Importar y conciliar'}
        </Button>
      </div>
    </Modal>
  )
}

function StatementView({ id, canWrite, onBack }: { id: string; canWrite: boolean; onBack: () => void }) {
  const queryClient = useQueryClient()
  const role = useActiveRole()
  const [filter, setFilter] = useState<'ALL' | 'PENDING' | 'DIFF'>('ALL')
  const [picking, setPicking] = useState<BankLine | null>(null)
  const [ignoring, setIgnoring] = useState<BankLine | null>(null)
  const [balance, setBalance] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const { data, isLoading } = useQuery({
    queryKey: ['bank-statements', 'detail', id],
    queryFn: async () => (await api.get<BankStatementDetail>(`/bank-statements/${id}`)).data,
  })

  function store(detail: BankStatementDetail) {
    queryClient.setQueryData(['bank-statements', 'detail', id], detail)
    void queryClient.invalidateQueries({ queryKey: ['bank-statements', 'list'] })
  }

  const action = useMutation({
    mutationFn: async ({ path, body }: { path: string; body?: unknown }) =>
      (await api.post<BankStatementDetail>(`/bank-statements/${id}${path}`, body ?? {})).data,
    onSuccess: (detail) => {
      store(detail)
      setNotice(null)
    },
    onError: (err) => setNotice(errorMessage(err)),
  })

  const autoMatch = useMutation({
    mutationFn: async () =>
      (await api.post<{ confirmed: number; detail: BankStatementDetail }>(`/bank-statements/${id}/auto-match`)).data,
    onSuccess: (result) => {
      store(result.detail)
      setNotice(
        result.confirmed
          ? `Se conciliaron ${result.confirmed} renglones que sólo tenían un movimiento posible.`
          : 'No hay coincidencias seguras: revisa las propuestas una por una.',
      )
    },
    onError: (err) => setNotice(errorMessage(err)),
  })

  const cancel = useMutation({
    mutationFn: async () => api.post(`/bank-statements/${id}/cancel`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['bank-statements'] })
      onBack()
    },
    onError: (err) => setNotice(errorMessage(err)),
  })

  const saveBalance = useMutation({
    mutationFn: async (value: string) =>
      (await api.patch<BankStatementDetail>(`/bank-statements/${id}`, { closing_balance: value || null })).data,
    onSuccess: (detail) => {
      store(detail)
      setBalance(null)
      setNotice(null)
    },
    onError: (err) => setNotice(errorMessage(err)),
  })

  if (isLoading || !data) return <div className="h-64 animate-pulse rounded-xl bg-surface-2" />

  const { statement, summary, lines } = data
  const open = statement.status === 'OPEN'
  const editable = open && canWrite
  const shown = lines.filter((line) =>
    filter === 'PENDING'
      ? line.status === 'PENDING'
      : filter === 'DIFF'
        ? line.status === 'MATCHED' && Number(line.difference ?? 0) !== 0
        : true,
  )
  const busy = action.isPending || autoMatch.isPending

  return (
    <div>
      <button type="button" className="mb-3 text-sm text-muted hover:text-ink" onClick={onBack}>
        ← Conciliaciones
      </button>
      <PageHeader
        title={statement.account_name ?? 'Conciliación'}
        description={`${formatDate(statement.period_start)} – ${formatDate(statement.period_end)} · ${statement.filename}`}
        actions={
          <>
            <Pill config={STATUS[statement.status] ?? STATUS.OPEN} />
            {editable && summary.pending_count > 0 ? (
              <Button variant="secondary" disabled={busy} onClick={() => autoMatch.mutate()}>
                Conciliar lo seguro
              </Button>
            ) : null}
            {editable ? (
              <Button
                disabled={busy || summary.pending_count > 0 || summary.closing_balance === null}
                title={
                  summary.pending_count > 0
                    ? 'Quedan renglones pendientes'
                    : summary.closing_balance === null
                      ? 'Falta el saldo final del estado de cuenta'
                      : undefined
                }
                onClick={() => action.mutate({ path: '/close' })}
              >
                Cerrar conciliación
              </Button>
            ) : null}
            {statement.status === 'CLOSED' && ADMIN_ROLES.includes(role ?? '') ? (
              <Button variant="secondary" disabled={busy} onClick={() => action.mutate({ path: '/reopen' })}>
                Reabrir
              </Button>
            ) : null}
          </>
        }
      />

      {notice ? <p className="mb-4 rounded bg-accent-soft px-3 py-2 text-sm text-ink">{notice}</p> : null}

      <div className="mb-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card>
          <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted">Saldo en banco</div>
          <div className="mt-2">
            {summary.closing_balance !== null ? (
              <Money value={summary.closing_balance} size="lg" />
            ) : (
              <span className="text-sm text-muted">Sin capturar</span>
            )}
          </div>
          {editable ? (
            <button type="button" className="mt-1 text-xs text-accent" onClick={() => setBalance(summary.closing_balance ?? '')}>
              {summary.closing_balance !== null ? 'Corregir' : 'Capturar saldo final'}
            </button>
          ) : null}
        </Card>
        <Card>
          <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted">Saldo en libros</div>
          <div className="mt-2">
            <Money value={summary.book_balance} size="lg" />
          </div>
          <div className="mt-1 text-xs text-muted">Al {formatDate(statement.period_end)}</div>
        </Card>
        <Card>
          <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted">En tránsito</div>
          <div className="mt-2 space-y-0.5 text-sm">
            <div className="flex justify-between gap-3">
              <span className="text-muted">Entradas sin llegar</span>
              <Signed value={summary.in_transit_in} />
            </div>
            <div className="flex justify-between gap-3">
              <span className="text-muted">Salidas sin cobrar</span>
              <Signed value={summary.in_transit_out} />
            </div>
          </div>
        </Card>
        <Card>
          <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted">Sin explicar</div>
          <div className="mt-2">
            {summary.unexplained !== null ? (
              <Money value={summary.unexplained} size="lg" tone={Number(summary.unexplained) === 0 ? 'pos' : 'neg'} />
            ) : (
              <span className="text-sm text-muted">Falta el saldo en banco</span>
            )}
          </div>
          <div className="mt-1 text-xs text-muted">
            {summary.unexplained !== null && Number(summary.unexplained) === 0
              ? 'Banco y libros cuadran'
              : 'Banco menos libros y partidas identificadas'}
          </div>
        </Card>
      </div>

      {summary.alerts.length > 0 ? (
        <div className="mb-4 space-y-1.5">
          {summary.alerts.map((alert) => (
            <div
              key={alert.kind}
              className={`flex flex-wrap items-baseline justify-between gap-2 rounded border px-3 py-2 text-sm ${
                alert.kind === 'BOOK_UNMATCHED' || alert.kind === 'PENDING'
                  ? 'border-warn/30 bg-warn/5 text-ink'
                  : 'border-neg/30 bg-neg/5 text-ink'
              }`}
            >
              <span>
                <span className="figures font-medium">{alert.count}</span> · {alert.message}
              </span>
              {alert.amount !== null ? <Signed value={alert.amount} /> : null}
            </div>
          ))}
        </div>
      ) : (
        <p className="mb-4 rounded border border-pos/30 bg-pos/5 px-3 py-2 text-sm">Sin diferencias por revisar.</p>
      )}

      <div className="mb-2 flex flex-wrap gap-1.5 text-sm">
        {(
          [
            ['ALL', `Todos (${summary.lines_count})`],
            ['PENDING', `Pendientes (${summary.pending_count})`],
            ['DIFF', `Con diferencia (${summary.differences_count})`],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            type="button"
            className={`rounded-full px-3 py-1 ${filter === key ? 'bg-ink text-bg' : 'bg-surface-2 text-ink-soft hover:text-ink'}`}
            onClick={() => setFilter(key)}
          >
            {label}
          </button>
        ))}
      </div>

      <Table headers={['Fecha', 'Renglón del banco', 'Importe', 'Estado', 'Movimiento registrado', '']} secondary={[4]}>
        {shown.length === 0 ? (
          <tr>
            <td colSpan={6} className="px-4 py-8 text-center text-sm text-muted">
              No hay renglones en este filtro.
            </td>
          </tr>
        ) : (
          shown.map((line) => {
            const suggestion = line.suggestions[0]
            const difference = Number(line.difference ?? 0)
            return (
              <tr key={line.id} className="align-top">
                <td className="whitespace-nowrap px-4 py-3 text-ink-soft">{formatDate(line.date)}</td>
                <td className="px-4 py-3">
                  <div>{line.description}</div>
                  {line.reference ? <div className="font-mono text-xs text-muted">{line.reference}</div> : null}
                </td>
                <td className="whitespace-nowrap px-4 py-3 text-right">
                  <Signed value={line.amount} />
                </td>
                <td className="px-4 py-3">
                  <Pill config={LINE_STATUS[line.status] ?? LINE_STATUS.PENDING} />
                </td>
                <td className="px-4 py-3 text-sm">
                  {line.status === 'MATCHED' ? (
                    <>
                      {line.matches.map((t) => (
                        <TransactionLine key={t.id} transaction={t} />
                      ))}
                      {difference !== 0 ? (
                        <div className="mt-1 text-xs font-medium text-neg">Diferencia {formatMoney(line.difference)}</div>
                      ) : null}
                    </>
                  ) : line.status === 'IGNORED' ? (
                    <span className="text-muted">{line.note}</span>
                  ) : suggestion ? (
                    <>
                      <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted">
                        {suggestion.kind === 'GROUP' ? 'Propuesta: varios movimientos del día' : 'Propuesta'}
                      </div>
                      {suggestion.transactions.map((t) => (
                        <TransactionLine key={t.id} transaction={t} />
                      ))}
                    </>
                  ) : (
                    <span className="text-muted">Sin movimiento que coincida</span>
                  )}
                </td>
                <td className="whitespace-nowrap px-4 py-3 text-right">
                  {!editable ? null : line.status === 'PENDING' ? (
                    <div className="flex flex-wrap justify-end gap-1.5">
                      {suggestion ? (
                        <Button
                          className="!px-2.5 !py-1 text-xs"
                          disabled={busy}
                          onClick={() =>
                            action.mutate({
                              path: `/lines/${line.id}/match`,
                              body: { transaction_ids: suggestion.transactions.map((t) => t.id) },
                            })
                          }
                        >
                          Confirmar
                        </Button>
                      ) : null}
                      <Button variant="secondary" className="!px-2.5 !py-1 text-xs" onClick={() => setPicking(line)}>
                        Buscar
                      </Button>
                      <Button variant="ghost" className="!px-2.5 !py-1 text-xs" onClick={() => setIgnoring(line)}>
                        No corresponde
                      </Button>
                    </div>
                  ) : (
                    <Button
                      variant="ghost"
                      className="!px-2.5 !py-1 text-xs"
                      disabled={busy}
                      onClick={() => action.mutate({ path: `/lines/${line.id}/reset` })}
                    >
                      Deshacer
                    </Button>
                  )}
                </td>
              </tr>
            )
          })
        )}
      </Table>

      {open && data.in_transit.length > 0 ? (
        <div className="mt-8">
          <h2 className="mb-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-muted">
            Registrado en el periodo y sin aparecer en el banco
          </h2>
          <Table headers={['Fecha', 'Movimiento', 'Importe']}>
            {data.in_transit.map((t) => (
              <tr key={t.id}>
                <td className="whitespace-nowrap px-4 py-2.5 text-ink-soft">{formatDate(t.date)}</td>
                <td className="px-4 py-2.5">
                  {t.description}
                  {t.reference ? <span className="ml-2 font-mono text-xs text-muted">{t.reference}</span> : null}
                </td>
                <td className="px-4 py-2.5 text-right">
                  <Signed value={t.amount} />
                </td>
              </tr>
            ))}
          </Table>
        </div>
      ) : null}

      {editable ? (
        <div className="mt-8 text-right">
          <Button
            variant="danger"
            disabled={cancel.isPending}
            onClick={() => {
              if (window.confirm('Se descarta este estado de cuenta y sus coincidencias. Los movimientos no cambian.'))
                cancel.mutate()
            }}
          >
            Descartar estado de cuenta
          </Button>
        </div>
      ) : null}

      {picking ? (
        <PickModal
          statementId={id}
          line={picking}
          onClose={() => setPicking(null)}
          onConfirm={(ids) => {
            action.mutate({ path: `/lines/${picking.id}/match`, body: { transaction_ids: ids } })
            setPicking(null)
          }}
        />
      ) : null}

      {ignoring ? (
        <IgnoreModal
          line={ignoring}
          onClose={() => setIgnoring(null)}
          onConfirm={(note) => {
            action.mutate({ path: `/lines/${ignoring.id}/ignore`, body: { note } })
            setIgnoring(null)
          }}
        />
      ) : null}

      {balance !== null ? (
        <Modal title="Saldo final" open onClose={() => setBalance(null)}>
          <h2 className="font-display text-lg font-semibold tracking-tight">Saldo final del estado de cuenta</h2>
          <p className="mt-1 text-sm text-muted">El saldo con el que cierra el periodo según el banco.</p>
          <div className="mt-4">
            <TextInput
              label="Saldo final"
              inputMode="decimal"
              autoFocus
              value={balance}
              onChange={(e) => setBalance(e.target.value)}
            />
          </div>
          <div className="mt-6 flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setBalance(null)}>
              Cancelar
            </Button>
            <Button disabled={saveBalance.isPending} onClick={() => saveBalance.mutate(balance.trim())}>
              Guardar
            </Button>
          </div>
        </Modal>
      ) : null}
    </div>
  )
}

function TransactionLine({ transaction }: { transaction: BankTransactionBrief }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <span className="min-w-0 truncate">
        <span className="text-muted">{formatDate(transaction.date)}</span> {transaction.description}
      </span>
      <Signed value={transaction.amount} />
    </div>
  )
}

function PickModal({
  statementId,
  line,
  onClose,
  onConfirm,
}: {
  statementId: string
  line: BankLine
  onClose: () => void
  onConfirm: (ids: string[]) => void
}) {
  const [search, setSearch] = useState('')
  const [chosen, setChosen] = useState<Record<string, number>>({})
  const { data, isLoading } = useQuery({
    queryKey: ['bank-statements', 'candidates', statementId, line.id, search],
    queryFn: async () =>
      (
        await api.get<BankTransactionBrief[]>(`/bank-statements/${statementId}/lines/${line.id}/candidates`, {
          params: { search: search || undefined },
        })
      ).data,
  })
  const total = Object.values(chosen).reduce((sum, amount) => sum + amount, 0)
  const difference = Math.round((Number(line.amount) - total) * 100) / 100
  const ids = Object.keys(chosen)

  return (
    <Modal title="Buscar movimiento" open onClose={onClose} size="lg">
      <h2 className="font-display text-lg font-semibold tracking-tight">¿A qué movimientos corresponde?</h2>
      <p className="mt-1 text-sm text-muted">
        {formatDate(line.date)} · {line.description} · <span className="figures">{formatMoney(line.amount)}</span>. Puedes
        elegir varios: un depósito puede liquidar varias ventas.
      </p>
      <div className="mt-4">
        <TextInput
          label="Buscar por concepto, referencia o importe"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>
      <div className="mt-3 max-h-72 overflow-auto rounded border border-border">
        {isLoading ? (
          <div className="h-24 animate-pulse bg-surface-2" />
        ) : (data ?? []).length === 0 ? (
          <p className="px-4 py-8 text-center text-sm text-muted">
            No hay movimientos libres cerca de esa fecha. Regístralo primero y vuelve a buscar.
          </p>
        ) : (
          <table className="w-full text-sm">
            <tbody className="divide-y divide-border">
              {data!.map((t) => (
                <tr key={t.id} className="cursor-pointer hover:bg-surface-2">
                  <td className="px-3 py-2">
                    <input
                      type="checkbox"
                      aria-label={`Elegir ${t.description}`}
                      checked={t.id in chosen}
                      onChange={(e) => {
                        const next = { ...chosen }
                        if (e.target.checked) next[t.id] = Number(t.amount)
                        else delete next[t.id]
                        setChosen(next)
                      }}
                    />
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-muted">{formatDate(t.date)}</td>
                  <td className="px-3 py-2">
                    {t.description}
                    {t.reference ? <span className="ml-2 font-mono text-xs text-muted">{t.reference}</span> : null}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <Signed value={t.amount} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
        <span className={`text-sm ${ids.length && difference !== 0 ? 'text-neg' : 'text-muted'}`}>
          {ids.length === 0
            ? 'Elige al menos un movimiento.'
            : difference === 0
              ? 'El importe coincide.'
              : `Quedaría una diferencia de ${formatMoney(difference)}, visible como alerta.`}
        </span>
        <div className="flex gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancelar
          </Button>
          <Button disabled={ids.length === 0} onClick={() => onConfirm(ids)}>
            {difference === 0 || ids.length === 0 ? 'Conciliar' : 'Conciliar con diferencia'}
          </Button>
        </div>
      </div>
    </Modal>
  )
}

function IgnoreModal({
  line,
  onClose,
  onConfirm,
}: {
  line: BankLine
  onClose: () => void
  onConfirm: (note: string) => void
}) {
  const [note, setNote] = useState('')
  return (
    <Modal title="No corresponde" open onClose={onClose}>
      <h2 className="font-display text-lg font-semibold tracking-tight">Este renglón no corresponde a ningún movimiento</h2>
      <p className="mt-1 text-sm text-muted">
        {formatDate(line.date)} · {line.description} · <span className="figures">{formatMoney(line.amount)}</span>. Si es
        dinero real que falta registrar (una comisión, un depósito), regístralo y lígalo; usa esto sólo cuando no deba
        estar en tus libros.
      </p>
      <div className="mt-4">
        <TextInput
          label="Motivo"
          autoFocus
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="Ej. traspaso entre cuentas propias ya registrado en otro renglón"
        />
      </div>
      <div className="mt-6 flex justify-end gap-2">
        <Button variant="ghost" onClick={onClose}>
          Cancelar
        </Button>
        <Button disabled={!note.trim()} onClick={() => onConfirm(note.trim())}>
          Marcar
        </Button>
      </div>
    </Modal>
  )
}
