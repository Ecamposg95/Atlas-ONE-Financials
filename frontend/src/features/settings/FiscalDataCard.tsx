import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { api, errorMessage } from '@/api/client'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Table'
import { FiscalFields, ReadinessPanel, fiscalPayload, type FiscalForm } from '@/features/fiscal/FiscalFields'
import { usePermissions } from '@/lib/permissions'
import { useAuthStore } from '@/stores/authStore'
import type { Organization } from '@/types/api'

/** Datos de la empresa como emisora de facturas, con el indicador de lo que falta. */
export function FiscalDataCard() {
  const organization = useAuthStore((state) => state.organization)
  const { canAdmin: canEdit } = usePermissions()
  const [form, setForm] = useState<FiscalForm>({
    legal_name: organization?.legal_name ?? '',
    tax_id: organization?.tax_id ?? '',
    fiscal_regime: organization?.fiscal_regime ?? '',
    fiscal_postal_code: organization?.fiscal_postal_code ?? '',
  })
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const saveMutation = useMutation({
    mutationFn: async () => (await api.patch<Organization>('/organizations/current', fiscalPayload(form))).data,
    onSuccess: (updated) => {
      useAuthStore.setState((state) => ({
        organization: updated,
        organizations: state.organizations.map((company) => (company.id === updated.id ? updated : company)),
      }))
      setError(null)
      setMessage('Datos fiscales guardados.')
    },
    onError: (err) => {
      setMessage(null)
      setError(errorMessage(err))
    },
  })

  return (
    <Card className="mt-6 max-w-lg">
      <h2 className="font-display text-lg font-semibold">Datos fiscales</h2>
      <p className="mt-1 text-sm text-muted">
        Cópialos de tu constancia de situación fiscal. Quedan guardados para cuando puedas facturar desde Atlas Financials; la emisión de facturas todavía no está disponible.
      </p>
      <div className="mt-4">
        <ReadinessPanel readiness={organization?.fiscal_readiness} subject="Tu empresa" />
      </div>
      <form
        onSubmit={(event) => {
          event.preventDefault()
          saveMutation.mutate()
        }}
        className="mt-4 space-y-4"
      >
        <fieldset disabled={!canEdit} className="space-y-4">
          <FiscalFields form={form} onChange={setForm} />
        </fieldset>
        {!canEdit ? <p className="text-xs text-muted">Sólo el dueño o un administrador pueden cambiarlos.</p> : null}
        {message ? <p className="text-sm text-pos">{message}</p> : null}
        {error ? <p className="text-sm text-neg">{error}</p> : null}
        {canEdit ? (
          <Button type="submit" disabled={saveMutation.isPending}>
            Guardar datos fiscales
          </Button>
        ) : null}
      </form>
    </Card>
  )
}
