import { useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import { SelectInput, TextInput } from '@/components/ui/Field'
import type { FiscalReadiness, Page, SatOption } from '@/types/api'

type SatCatalog = 'c_RegimenFiscal' | 'c_UsoCFDI' | 'c_FormaPago' | 'c_MetodoPago'

/**
 * Claves vigentes de un catálogo del SAT. El filtro por tipo de persona (del RFC)
 * y por régimen lo hace el backend: la UI no decide qué es válido.
 */
export function useSatCatalog(name: SatCatalog, params: { rfc?: string; regimen?: string } = {}) {
  const clean = Object.fromEntries(Object.entries(params).filter(([, value]) => value))
  return useQuery({
    queryKey: ['sat-catalog', name, clean],
    queryFn: async () => (await api.get<Page<SatOption>>(`/fiscal-mx/catalogs/${name}`, { params: clean })).data.items,
    staleTime: 60 * 60 * 1000,
  })
}

export function asOptions(items: SatOption[] | undefined, current: string) {
  const options = (items ?? []).map((item) => ({ value: item.clave, label: `${item.clave} · ${item.descripcion}` }))
  // Un valor guardado que ya no aparece (otro tipo de persona, clave vencida) se
  // sigue mostrando para que el indicador explique qué hay que corregir.
  if (current && !options.some((option) => option.value === current)) {
    options.unshift({ value: current, label: `${current} · revisa esta clave` })
  }
  return options
}

export interface FiscalForm {
  legal_name: string
  tax_id: string
  fiscal_regime: string
  fiscal_postal_code: string
  default_cfdi_use?: string
}

export const EMPTY_FISCAL_FORM: FiscalForm = {
  legal_name: '',
  tax_id: '',
  fiscal_regime: '',
  fiscal_postal_code: '',
}

/** Valores vacíos como null: así se puede borrar un dato ya guardado. */
export function fiscalPayload(form: FiscalForm): Record<string, string | null> {
  return Object.fromEntries(Object.entries(form).map(([key, value]) => [key, value ? value : null]))
}

const GENERIC_RFCS = ['XAXX010101000', 'XEXX010101000']

/**
 * RFC, razón social, régimen y código postal fiscal; con `receptor`, además el uso
 * de CFDI por defecto. Los textos explican de dónde sale cada dato: la constancia.
 */
export function FiscalFields({
  form,
  onChange,
  receptor = false,
}: {
  form: FiscalForm
  onChange: (form: FiscalForm) => void
  receptor?: boolean
}) {
  const rfc = form.tax_id.replace(/\s/g, '').toUpperCase()
  const rfcComplete = rfc.length === 12 || rfc.length === 13
  const generic = GENERIC_RFCS.includes(rfc)
  const regimes = useSatCatalog('c_RegimenFiscal', rfcComplete ? { rfc } : {})
  const uses = useSatCatalog('c_UsoCFDI', {
    ...(rfcComplete ? { rfc } : {}),
    ...(form.fiscal_regime ? { regimen: form.fiscal_regime } : {}),
  })

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <TextInput
          label="RFC (opcional)"
          value={form.tax_id}
          maxLength={13}
          autoCapitalize="characters"
          hint={receptor ? 'Público en general: XAXX010101000. Extranjero: XEXX010101000.' : undefined}
          onChange={(event) => onChange({ ...form, tax_id: event.target.value.toUpperCase() })}
        />
        <TextInput
          label="Código postal fiscal (opcional)"
          value={form.fiscal_postal_code}
          inputMode="numeric"
          maxLength={5}
          disabled={receptor && generic}
          hint={receptor && generic ? 'Con RFC genérico se usa el de tu empresa.' : undefined}
          onChange={(event) => onChange({ ...form, fiscal_postal_code: event.target.value.replace(/\D/g, '') })}
        />
      </div>
      <TextInput
        label="Razón social (opcional)"
        value={form.legal_name}
        hint="Tal como aparece en la constancia de situación fiscal, sin S.A. de C.V."
        onChange={(event) => onChange({ ...form, legal_name: event.target.value })}
      />
      <SelectInput
        label="Régimen fiscal (opcional)"
        placeholder={regimes.isLoading ? 'Cargando…' : 'Sin capturar'}
        options={asOptions(regimes.data, form.fiscal_regime)}
        value={form.fiscal_regime}
        onChange={(event) => onChange({ ...form, fiscal_regime: event.target.value })}
      />
      {receptor ? (
        <SelectInput
          label="Uso de CFDI por defecto (opcional)"
          placeholder={uses.isLoading ? 'Cargando…' : 'Sin capturar'}
          options={asOptions(uses.data, form.default_cfdi_use ?? '')}
          value={form.default_cfdi_use ?? ''}
          onChange={(event) => onChange({ ...form, default_cfdi_use: event.target.value })}
        />
      ) : null}
    </div>
  )
}

/** Indicador de "listo para facturar": dice qué falta y qué conviene revisar. */
export function ReadinessPanel({ readiness, subject }: { readiness?: FiscalReadiness; subject: string }) {
  if (!readiness) return null
  return (
    <div className="rounded-panel border border-border bg-surface-2/60 p-3 text-sm" role="status">
      <div className="flex items-center gap-2">
        <ReadinessBadge readiness={readiness} />
        <span className="text-muted">
          {readiness.listo ? `${subject} tiene lo necesario para facturar.` : `A ${subject.toLowerCase()} le falta:`}
        </span>
      </div>
      {readiness.faltantes.length > 0 ? (
        <ul className="mt-2 list-disc space-y-0.5 pl-5 text-ink-soft">
          {readiness.faltantes.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      ) : null}
      {readiness.advertencias.length > 0 ? (
        <ul className="mt-2 space-y-0.5 text-warn">
          {readiness.advertencias.map((item) => (
            <li key={item}>Revisa: {item}</li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}

export function ReadinessBadge({ readiness }: { readiness?: FiscalReadiness }) {
  if (!readiness) return null
  const ready = readiness.listo
  return (
    <span
      className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${
        ready ? 'bg-pos/10 text-pos' : 'bg-warn/10 text-warn'
      }`}
      title={ready ? undefined : readiness.faltantes.join(' · ')}
    >
      {ready
        ? 'Listo para facturar'
        : readiness.faltantes.length === 1
          ? 'Falta 1 dato para facturar'
          : `Faltan ${readiness.faltantes.length} datos para facturar`}
    </span>
  )
}
