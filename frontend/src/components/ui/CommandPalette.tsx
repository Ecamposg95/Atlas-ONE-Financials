/** Paleta de comandos (⌘K / Ctrl+K): a cualquier pantalla o acción en dos teclas.
 *
 *  Sin librería: son dos listas estáticas (navegar y crear) con filtro por
 *  subcadena insensible a acentos. La robustez aquí es que no depende de la
 *  red: si la API está caída, la paleta sigue navegando.
 *
 *  R2·HU-21: con dos letras o más, además busca en los datos (ingresos,
 *  gastos, cuentas por pagar y cobrar, clientes y proveedores) y lo muestra
 *  debajo de los comandos.
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { api } from '@/api/client'
import { formatDate, formatMoney } from '@/lib/format'
import { usePermissions } from '@/lib/permissions'

export interface Command {
  label: string
  hint: string
  to: string
  keywords?: string
  /** Qué permiso exige: los comandos que el API rechazaría no se ofrecen. */
  requires?: 'write' | 'accounting'
  /** Resultado de búsqueda: fecha y monto bajo el título. */
  detail?: string
}

interface SearchHit {
  kind: string
  id: string
  title: string
  noun: string
  date: string | null
  amount: string | null
  status: string
  to: string
}

/** Espera a que el usuario deje de teclear antes de pedir al servidor. */
function useDebounced(value: string, delay = 250): string {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delay)
    return () => window.clearTimeout(timer)
  }, [value, delay])
  return debounced
}

const NAVIGATE: Command[] = [
  { label: 'Inicio', hint: 'Ir a', to: '/' },
  { label: 'Asistente', hint: 'Ir a', to: '/asistente', keywords: 'claude chat preguntar ia' },
  { label: 'Movimientos', hint: 'Ir a', to: '/movimientos' },
  { label: 'Análisis', hint: 'Ir a', to: '/analisis', keywords: 'terminal graficas series runway efectivo velas' },
  { label: 'Agentes', hint: 'Ir a', to: '/agentes', keywords: 'cfo treasury collections forecast equipo brief' },
  { label: 'Mis empresas', hint: 'Ir a', to: '/despacho', keywords: 'despacho cartera clientes cambiar empresa contador' },
  { label: 'Cuentas de dinero', hint: 'Ir a', to: '/cuentas', keywords: 'bancos tarjetas' },
  { label: 'Patrimonio', hint: 'Ir a', to: '/patrimonio', keywords: 'activos prestamos creditos' },
  { label: 'Importar', hint: 'Ir a', to: '/importar', keywords: 'toronja excel csv subir archivo ventas' },
  { label: 'Ingresos', hint: 'Ir a', to: '/ingresos', keywords: 'ventas' },
  { label: 'Gastos', hint: 'Ir a', to: '/gastos', keywords: 'compras' },
  { label: 'Por cobrar', hint: 'Ir a', to: '/por-cobrar', keywords: 'cxc cartera facturas' },
  { label: 'Por pagar', hint: 'Ir a', to: '/por-pagar', keywords: 'cxp deudas' },
  { label: 'Clientes', hint: 'Ir a', to: '/clientes' },
  { label: 'Proveedores', hint: 'Ir a', to: '/proveedores' },
  { label: 'Proyectos', hint: 'Ir a', to: '/proyectos', keywords: 'rentabilidad margen' },
  { label: 'Reportes', hint: 'Ir a', to: '/reportes', keywords: 'estados financieros' },
  { label: 'Cartera y antigüedad', hint: 'Ir a', to: '/reportes?vista=cartera', keywords: 'dso vencido aging' },
  { label: 'Patrimonio neto', hint: 'Ir a', to: '/reportes?vista=patrimonio', keywords: 'net worth' },
  { label: 'IVA', hint: 'Ir a', to: '/reportes?vista=iva', keywords: 'impuestos sat' },
  { label: 'Contabilidad', hint: 'Ir a', requires: 'accounting', to: '/contabilidad', keywords: 'libro diario polizas' },
  { label: 'Balanza de comprobación', hint: 'Ir a', requires: 'accounting', to: '/contabilidad?vista=balanza', keywords: 'cargos abonos' },
  { label: 'Cierre de periodo', hint: 'Ir a', requires: 'accounting', to: '/contabilidad?vista=periodos', keywords: 'cerrar mes candado' },
  { label: 'Propuestas', hint: 'Ir a', to: '/propuestas', keywords: 'agentes aprobar' },
  { label: 'Configuración', hint: 'Ir a', to: '/configuracion', keywords: 'empresa equipo llaves agentes' },
]

const CREATE: Command[] = [
  { label: 'Nuevo ingreso', hint: 'Crear', requires: 'write', to: '/ingresos?nuevo=1', keywords: 'venta cobrar' },
  { label: 'Nuevo gasto', hint: 'Crear', requires: 'write', to: '/gastos?nuevo=1', keywords: 'compra pagar' },
  { label: 'Nueva cuenta por cobrar', hint: 'Crear', requires: 'write', to: '/por-cobrar?nueva=1', keywords: 'factura credito' },
  { label: 'Nueva cuenta por pagar', hint: 'Crear', requires: 'write', to: '/por-pagar?nueva=1' },
  { label: 'Traspaso entre cuentas', hint: 'Crear', requires: 'write', to: '/movimientos?transferir=1', keywords: 'transferencia' },
  { label: 'Nueva póliza de diario', hint: 'Crear', requires: 'accounting', to: '/contabilidad?nueva=poliza', keywords: 'asiento manual contador' },
  { label: 'Nuevo cliente', hint: 'Crear', requires: 'write', to: '/clientes?nuevo=1' },
  { label: 'Nuevo proveedor', hint: 'Crear', requires: 'write', to: '/proveedores?nuevo=1' },
  { label: 'Nueva cuenta de dinero', hint: 'Crear', requires: 'write', to: '/cuentas?nueva=1', keywords: 'banco tarjeta' },
  { label: 'Nuevo proyecto', hint: 'Crear', requires: 'write', to: '/proyectos?nuevo=1' },
]

function normalize(text: string): string {
  return text
    .toLowerCase()
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
}

export function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const navigate = useNavigate()
  const permissions = usePermissions()
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLDivElement>(null)

  const term = useDebounced(query.trim())
  const { data: hits, isFetching: searching } = useQuery({
    queryKey: ['search', term],
    queryFn: async () => (await api.get<{ items: SearchHit[] }>('/search', { params: { q: term } })).data.items,
    enabled: open && term.length >= 2,
    staleTime: 15_000,
  })
  const found: Command[] = useMemo(
    () =>
      term.length >= 2
        ? (hits ?? []).map((hit) => ({
            label: hit.title,
            hint: hit.noun,
            to: hit.to,
            detail: [
              hit.date ? formatDate(hit.date) : null,
              hit.amount !== null ? formatMoney(hit.amount) : null,
              hit.status === 'CANCELLED' ? 'cancelado' : null,
            ]
              .filter(Boolean)
              .join(' · '),
          }))
        : [],
    [hits, term],
  )

  const commands = useMemo(() => {
    const q = normalize(query.trim())
    const all = [...CREATE, ...NAVIGATE].filter(
      (command) =>
        !command.requires ||
        (command.requires === 'write' ? permissions.canWrite : permissions.canAccounting),
    )
    if (!q) return all
    // El título manda: "cier" debe poner "Cierre de periodo" antes que un
    // resultado cuyo keyword apenas contiene la subcadena ("finanCIERos").
    const score = (command: Command) => {
      const label = normalize(command.label)
      if (label.startsWith(q)) return 0
      if (label.includes(q)) return 1
      if (normalize(command.keywords ?? '').includes(q)) return 2
      return -1
    }
    return all
      .map((command) => ({ command, rank: score(command) }))
      .filter((item) => item.rank >= 0)
      .sort((a, b) => a.rank - b.rank)
      .map((item) => item.command)
  }, [query])
  const results = useMemo(() => [...commands, ...found], [commands, found])

  // Al abrir: foco al input y selección al principio.
  useEffect(() => {
    if (open) {
      setQuery('')
      setActive(0)
      // El input existe hasta después del render.
      requestAnimationFrame(() => inputRef.current?.focus())
    }
  }, [open])

  useEffect(() => setActive(0), [query])

  // La fila activa se mantiene visible al navegar con teclado.
  useEffect(() => {
    listRef.current
      ?.querySelector(`[data-index="${active}"]`)
      ?.scrollIntoView({ block: 'nearest' })
  }, [active])

  if (!open) return null

  const run = (command: Command) => {
    onClose()
    navigate(command.to)
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/45 px-4 pt-[6vh] sm:pt-[12vh]"
      onMouseDown={onClose}
      role="dialog"
      aria-modal="true"
      aria-label="Paleta de comandos"
    >
      <div
        className="w-full max-w-lg overflow-hidden rounded-xl border border-border bg-surface shadow-2xl"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'ArrowDown') {
              event.preventDefault()
              setActive((current) => Math.min(current + 1, results.length - 1))
            } else if (event.key === 'ArrowUp') {
              event.preventDefault()
              setActive((current) => Math.max(current - 1, 0))
            } else if (event.key === 'Enter' && results[active]) {
              run(results[active])
            } else if (event.key === 'Escape') {
              onClose()
            }
          }}
          placeholder="Busca una operación, un contacto, a dónde ir o qué crear…"
          className="w-full border-b border-border bg-transparent px-4 py-3.5 text-sm outline-none placeholder:text-muted"
        />
        <div ref={listRef} className="max-h-80 overflow-y-auto py-1.5">
          {results.length === 0 ? (
            <p className="px-4 py-6 text-center text-sm text-muted">
              {searching ? 'Buscando…' : 'Nada coincide. Prueba un concepto, un proveedor, un RFC o un monto.'}
            </p>
          ) : (
            results.map((command, index) => (
              <div key={command.to + command.label + index}>
                {index === commands.length && found.length > 0 ? (
                  <p className="border-t border-border px-4 pb-1 pt-2 text-[11px] uppercase tracking-wider text-muted">
                    En tus datos
                  </p>
                ) : null}
                <button
                  type="button"
                  data-index={index}
                  onClick={() => run(command)}
                  onMouseEnter={() => setActive(index)}
                  className={`flex w-full items-center justify-between px-4 py-2 text-left text-sm ${
                    index === active ? 'bg-accent-soft text-accent' : 'text-ink'
                  }`}
                >
                  <span className="min-w-0">
                    <span className="block truncate">{command.label}</span>
                    {command.detail ? (
                      <span className="figures block text-xs text-muted">{command.detail}</span>
                    ) : null}
                  </span>
                  <span
                    className={`ml-3 shrink-0 text-[11px] uppercase tracking-wider ${
                      index === active ? 'text-accent/70' : 'text-muted'
                    }`}
                  >
                    {command.hint}
                  </span>
                </button>
              </div>
            ))
          )}
          {searching && results.length > 0 ? (
            <p className="px-4 py-1.5 text-xs text-muted">Buscando en tus datos…</p>
          ) : null}
        </div>
        <div className="border-t border-border px-4 py-2 text-[11px] text-muted">
          <span className="figures">↑↓</span> moverse · <span className="figures">Enter</span>{' '}
          abrir · <span className="figures">Esc</span> cerrar
        </div>
      </div>
    </div>
  )
}
