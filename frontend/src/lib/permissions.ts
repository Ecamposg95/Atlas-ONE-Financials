/** Roles y permisos de la empresa activa, en un solo lugar.
 *
 *  Espejo de lo que exige el backend (`app/models/organization.py` y los
 *  `require_role` de cada router): la UI esconde o desactiva lo que el servidor
 *  rechazaría, pero la autoridad sigue siendo el backend. Si cambia una regla
 *  allá, cambia aquí y en ningún otro archivo.
 */

import { useActiveRole } from '@/lib/companies'

export type Role = 'OWNER' | 'ADMIN' | 'ACCOUNTANT' | 'MEMBER' | 'VIEWER'

/** WRITE_ROLES: registrar, editar, pagar y cancelar operaciones. */
const WRITE_ROLES: readonly string[] = ['OWNER', 'ADMIN', 'ACCOUNTANT', 'MEMBER']
/** ACCOUNTING_ROLES: Contabilidad, pólizas (ver y capturar), cierres y apertura. */
const ACCOUNTING_ROLES: readonly string[] = ['OWNER', 'ADMIN', 'ACCOUNTANT']
/** Datos de la empresa, equipo, catálogos, importación, autorizaciones y llaves. */
const ADMIN_ROLES: readonly string[] = ['OWNER', 'ADMIN']

export interface Permissions {
  role: string | null
  /** Registrar y modificar operaciones (ingresos, gastos, cuentas, contactos…). */
  canWrite: boolean
  /** Ver y capturar pólizas, cerrar meses y revisar la apertura. */
  canAccounting: boolean
  /** Configurar la empresa: datos, equipo, unidades, importación, llaves. */
  canAdmin: boolean
  isOwner: boolean
}

export function permissionsFor(role: string | null): Permissions {
  const has = (allowed: readonly string[]) => role !== null && allowed.includes(role)
  return {
    role,
    canWrite: has(WRITE_ROLES),
    canAccounting: has(ACCOUNTING_ROLES),
    canAdmin: has(ADMIN_ROLES),
    isOwner: role === 'OWNER',
  }
}

/** Permisos del usuario en la empresa activa. */
export function usePermissions(): Permissions {
  return permissionsFor(useActiveRole())
}

/** Motivos cortos para un control desactivado. */
export const NO_PERMISSION = {
  write: 'Tu permiso es de consulta: no puedes registrar ni cambiar operaciones.',
  admin: 'Sólo el dueño o un administrador pueden cambiar esto.',
} as const

/** Los nombres que ve el usuario: uno por rol, iguales en toda la app.
 *  `hint` dice lo que la persona PUEDE HACER (espejo de los permisos de arriba). */
export const ROLE_INFO: Record<Role, { label: string; hint: string }> = {
  OWNER: { label: 'Dueño', hint: 'Todo, y autoriza siempre' },
  ADMIN: {
    label: 'Administrador',
    hint: 'Invita gente, cambia los datos de la empresa y lleva la contabilidad',
  },
  ACCOUNTANT: {
    label: 'Contador',
    hint: 'Registra operaciones y lleva la contabilidad: pólizas, cierres de mes y año, y apertura',
  },
  MEMBER: { label: 'Captura', hint: 'Registra ingresos, gastos y pagos; no ve la contabilidad' },
  VIEWER: { label: 'Consulta', hint: 'Consulta sin poder cambiar nada' },
}

/** Roles que se pueden asignar a alguien del equipo (el dueño no se asigna). */
export const ASSIGNABLE_ROLES: Role[] = ['ADMIN', 'ACCOUNTANT', 'MEMBER', 'VIEWER']

export function roleLabel(role: string): string {
  return ROLE_INFO[role as Role]?.label ?? role
}
