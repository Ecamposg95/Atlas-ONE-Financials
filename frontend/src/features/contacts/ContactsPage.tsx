import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { api, errorMessage } from '@/api/client'
import { Button } from '@/components/ui/Button'
import { EmptyState } from '@/components/ui/EmptyState'
import { TextInput } from '@/components/ui/Field'
import { Modal } from '@/components/ui/Modal'
import { PageHeader } from '@/components/ui/PageHeader'
import { Table } from '@/components/ui/Table'
import { TableFooter } from '@/components/ui/Pagination'
import { FiscalFields, ReadinessBadge, ReadinessPanel, type FiscalForm } from '@/features/fiscal/FiscalFields'
import type { Contact, Page } from '@/types/api'
import { usePermissions } from '@/lib/permissions'

interface Config {
  resource: 'customers' | 'vendors'
  title: string
  description: string
  singular: string
  emptyTitle: string
  emptyMessage: string
}

export const CUSTOMERS_CONFIG: Config = {
  resource: 'customers',
  title: 'Clientes',
  description: 'A quién le vendes.',
  singular: 'Cliente',
  emptyTitle: 'Aún no tienes clientes',
  emptyMessage: 'Da de alta a tus clientes para saber quién te compra y quién te debe.',
}

export const VENDORS_CONFIG: Config = {
  resource: 'vendors',
  title: 'Proveedores',
  description: 'A quién le compras.',
  singular: 'Proveedor',
  emptyTitle: 'Aún no tienes proveedores',
  emptyMessage: 'Da de alta a tus proveedores para saber a quién le compras y a quién le debes.',
}

const EMPTY_FORM = {
  name: '',
  legal_name: '',
  tax_id: '',
  email: '',
  phone: '',
  notes: '',
  fiscal_regime: '',
  fiscal_postal_code: '',
  default_cfdi_use: '',
}

type ContactForm = typeof EMPTY_FORM

const FISCAL_KEYS = ['fiscal_regime', 'fiscal_postal_code', 'default_cfdi_use'] as const

function formFrom(contact: Contact): ContactForm {
  return {
    name: contact.name,
    legal_name: contact.legal_name ?? '',
    tax_id: contact.tax_id ?? '',
    email: contact.email ?? '',
    phone: contact.phone ?? '',
    notes: contact.notes ?? '',
    fiscal_regime: contact.fiscal_regime ?? '',
    fiscal_postal_code: contact.fiscal_postal_code ?? '',
    default_cfdi_use: contact.default_cfdi_use ?? '',
  }
}

export function ContactsPage({ config }: { config: Config }) {
  const { canWrite } = usePermissions()
  const queryClient = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()
  const [modalOpen, setModalOpen] = useState(searchParams.has('nuevo'))
  // `?q=` llega del buscador general (Ctrl K).
  const [search, setSearch] = useState(searchParams.get('q') ?? '')
  const [offset, setOffset] = useState(0)
  const [form, setForm] = useState<ContactForm>(EMPTY_FORM)
  const [editing, setEditing] = useState<Contact | null>(null)
  const [error, setError] = useState<string | null>(null)
  const isCustomer = config.resource === 'customers'

  const { data, isLoading } = useQuery({
    queryKey: [config.resource, search, offset],
    queryFn: async () =>
      (
        await api.get<Page<Contact>>(`/${config.resource}`, {
          params: { ...(search ? { q: search } : {}), offset },
        })
      ).data,
  })

  const saveMutation = useMutation({
    mutationFn: async () => {
      const entries = Object.entries(form).filter(
        ([key]) => isCustomer || !(FISCAL_KEYS as readonly string[]).includes(key),
      )
      if (editing) {
        // Sólo lo que cambió (un RFC viejo mal capturado no bloquea editar el teléfono);
        // lo vacío viaja como null para poder borrar un dato.
        const before = formFrom(editing)
        const payload = Object.fromEntries(
          entries
            .filter(([key, value]) => before[key as keyof ContactForm] !== value)
            .map(([key, value]) => [key, value === '' && key !== 'name' ? null : value]),
        )
        await api.patch(`/${config.resource}/${editing.id}`, payload)
      } else {
        await api.post(`/${config.resource}`, Object.fromEntries(entries.filter(([, value]) => value !== '')))
      }
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: [config.resource] })
      closeModal()
    },
    onError: (err) => setError(errorMessage(err)),
  })

  function openEdit(contact: Contact) {
    setEditing(contact)
    setForm(formFrom(contact))
    setError(null)
    setModalOpen(true)
  }

  function closeModal() {
    setModalOpen(false)
    setEditing(null)
    setForm(EMPTY_FORM)
    setError(null)
    if (searchParams.has('nuevo')) {
      searchParams.delete('nuevo')
      setSearchParams(searchParams, { replace: true })
    }
  }

  const items = data?.items ?? []

  return (
    <div>
      <PageHeader
        title={config.title}
        description={config.description}
        actions={canWrite ? <Button onClick={() => setModalOpen(true)}>+ {config.singular}</Button> : undefined}
      >
        <input
          type="search"
          placeholder={`Buscar ${config.title.toLowerCase()}…`}
          value={search}
          onChange={(event) => {
            setSearch(event.target.value)
            setOffset(0)
          }}
          className="w-full max-w-xs rounded border border-border bg-surface px-3 py-2 text-sm"
        />
      </PageHeader>

      {isLoading ? (
        <div className="h-48 animate-pulse rounded-xl bg-surface-2" />
      ) : items.length === 0 ? (
        <EmptyState
          title={config.emptyTitle}
          message={config.emptyMessage}
          action={
            canWrite ? (
              <Button onClick={() => setModalOpen(true)}>Agregar {config.singular.toLowerCase()}</Button>
            ) : undefined
          }
        />
      ) : (
        <Table
          headers={isCustomer ? ['Nombre', 'RFC', 'Correo', 'Teléfono', 'Datos fiscales'] : ['Nombre', 'RFC', 'Correo', 'Teléfono']}
          footer={<TableFooter page={data!} onOffsetChange={setOffset} noun={config.title.toLowerCase()} />}
        >
          {items.map((contact) => (
            <tr
              key={contact.id}
              className={canWrite ? 'cursor-pointer hover:bg-surface-2/50' : undefined}
              onClick={canWrite ? () => openEdit(contact) : undefined}
              title={canWrite ? 'Ver y editar la ficha' : undefined}
            >
              <td className="px-4 py-2.5">
                <div className="font-medium">{contact.name}</div>
                {contact.legal_name ? <div className="text-xs text-muted">{contact.legal_name}</div> : null}
              </td>
              <td className="px-4 py-2.5 text-muted">{contact.tax_id ?? '—'}</td>
              <td className="px-4 py-2.5 text-muted">{contact.email ?? '—'}</td>
              <td className="px-4 py-2.5 text-muted">{contact.phone ?? '—'}</td>
              {isCustomer ? (
                <td className="px-4 py-2.5">
                  <ReadinessBadge readiness={contact.fiscal_readiness} />
                </td>
              ) : null}
            </tr>
          ))}
        </Table>
      )}

      <Modal
        title={editing ? editing.name : `Nuevo ${config.singular.toLowerCase()}`}
        open={modalOpen}
        onClose={closeModal}
      >
        <form
          onSubmit={(event) => {
            event.preventDefault()
            saveMutation.mutate()
          }}
          className="space-y-4"
        >
          <TextInput
            label="Nombre"
            required
            autoFocus
            value={form.name}
            onChange={(event) => setForm({ ...form, name: event.target.value })}
          />
          {isCustomer ? null : (
            <div className="grid grid-cols-2 gap-4">
              <TextInput
                label="Razón social (opcional)"
                value={form.legal_name}
                onChange={(event) => setForm({ ...form, legal_name: event.target.value })}
              />
              <TextInput
                label="RFC (opcional)"
                value={form.tax_id}
                onChange={(event) => setForm({ ...form, tax_id: event.target.value })}
              />
            </div>
          )}
          <div className="grid grid-cols-2 gap-4">
            <TextInput
              label="Correo (opcional)"
              type="email"
              value={form.email}
              onChange={(event) => setForm({ ...form, email: event.target.value })}
            />
            <TextInput
              label="Teléfono (opcional)"
              value={form.phone}
              onChange={(event) => setForm({ ...form, phone: event.target.value })}
            />
          </div>
          <TextInput
            label="Notas (opcional)"
            value={form.notes}
            onChange={(event) => setForm({ ...form, notes: event.target.value })}
          />
          {isCustomer ? (
            <section className="space-y-3 border-t border-border pt-4">
              <div>
                <h3 className="text-sm font-semibold">Datos fiscales</h3>
                <p className="text-xs text-muted">Pídele al cliente su constancia de situación fiscal.</p>
              </div>
              {editing ? <ReadinessPanel readiness={editing.fiscal_readiness} subject="Este cliente" /> : null}
              <FiscalFields
                receptor
                form={form as FiscalForm}
                onChange={(fiscal) => setForm({ ...form, ...fiscal, default_cfdi_use: fiscal.default_cfdi_use ?? '' })}
              />
            </section>
          ) : null}
          {error ? <p className="text-sm text-neg">{error}</p> : null}
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="ghost" onClick={closeModal}>
              Cancelar
            </Button>
            <Button type="submit" disabled={saveMutation.isPending}>
              Guardar
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  )
}
