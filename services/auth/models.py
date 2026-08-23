"""
Auth Service — User database model.

Tables:
  - users: email, bcrypt-hashed password, role, timestamps
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, Integer, String

from core.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(100), nullable=False)
    password_hash = Column(String(255), nullable=False)  # bcrypt hash
    role = Column(String(20), nullable=False, default="customer")
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(UTC))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))

    def __repr__(self):
        return f"<User {self.email} role={self.role}>"


class Tenant(Base):
    """
    Tenant entity representing B2B merchant accounts.
    Stores public API Key and private shared secret used for HMAC request verification.
    """
    __tablename__ = "tenants"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String(64), unique=True, nullable=False, index=True, default=lambda: f"TENANT-{uuid.uuid4().hex[:8].upper()}")
    name = Column(String(100), nullable=False)
    email = Column(String(255), nullable=False)
    api_key = Column(String(128), unique=True, nullable=False, index=True)
    api_secret = Column(String(128), nullable=False)  # Shared secret for HMAC-SHA256
    quota_limit_per_day = Column(Integer, nullable=False, default=1000)
    is_active = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(UTC))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))

    def __repr__(self):
        return f"<Tenant {self.name} id={self.tenant_id} key={self.api_key[:12]}...>"

