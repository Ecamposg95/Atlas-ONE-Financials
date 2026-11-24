from sqlalchemy import Column, DateTime, Integer, String

from app.database import Base
from app.models.mixins import AuditMixin, UUIDPKMixin


class User(Base, UUIDPKMixin, AuditMixin):
    __tablename__ = "users"

    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    name = Column(String(255), nullable=False)
    status = Column(String(20), nullable=False, default="ACTIVE")
    # Bloqueo temporal por contraseñas fallidas consecutivas (app/domains/auth/service.py).
    failed_login_count = Column(Integer, nullable=False, default=0, server_default="0")
    locked_until = Column(DateTime(timezone=True), nullable=True)
