from sqlalchemy import Column, String

from app.database import Base
from app.models.mixins import AuditMixin, SoftDeleteMixin, TenantMixin, UUIDPKMixin


class _ContactColumns:
    name = Column(String(255), nullable=False)
    legal_name = Column(String(255), nullable=True)
    tax_id = Column(String(20), nullable=True)
    email = Column(String(255), nullable=True)
    phone = Column(String(30), nullable=True)
    notes = Column(String(1000), nullable=True)
    status = Column(String(20), nullable=False, default="ACTIVE")


class _ReceptorColumns:
    """Receptor de CFDI: razón social = legal_name y RFC = tax_id; el resto, claves del SAT."""

    fiscal_regime = Column(String(3), nullable=True)  # c_RegimenFiscal
    fiscal_postal_code = Column(String(5), nullable=True)  # c_CodigoPostal (domicilio fiscal)
    default_cfdi_use = Column(String(4), nullable=True)  # c_UsoCFDI


class Customer(Base, UUIDPKMixin, TenantMixin, AuditMixin, SoftDeleteMixin, _ContactColumns, _ReceptorColumns):
    __tablename__ = "customers"


class Vendor(Base, UUIDPKMixin, TenantMixin, AuditMixin, SoftDeleteMixin, _ContactColumns):
    __tablename__ = "vendors"
