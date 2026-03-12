from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.db_manager import Base

if TYPE_CHECKING:
    from .memberships import TenantMembership
    from .users import User


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    bot_token: Mapped[str | None] = mapped_column(String(255), nullable=True)
    domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    admin_api_key: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    settings: Mapped["TenantSettings"] = relationship(
        "TenantSettings",
        back_populates="tenant",
        cascade="all, delete-orphan",
        uselist=False,
    )
    users: Mapped[list["User"]] = relationship(
        "User",
        back_populates="tenant",
    )
    memberships: Mapped[list["TenantMembership"]] = relationship(
        "TenantMembership",
        back_populates="tenant",
        cascade="all, delete-orphan",
    )


class TenantSettings(Base):
    __tablename__ = "tenant_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )

    locale: Mapped[str] = mapped_column(String(10), default="ru", nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Moscow", nullable=False)
    currency_code: Mapped[str] = mapped_column(String(8), default="RUB", nullable=False)

    storefront_title: Mapped[str] = mapped_column(String(255), nullable=False)
    support_label: Mapped[str] = mapped_column(String(255), default="Поддержка", nullable=False)
    owner_title: Mapped[str] = mapped_column(String(255), default="Владелец", nullable=False)
    staff_title: Mapped[str] = mapped_column(String(255), default="Сотрудник", nullable=False)

    welcome_text_client: Mapped[str | None] = mapped_column(Text, nullable=True)
    welcome_text_staff: Mapped[str | None] = mapped_column(Text, nullable=True)
    welcome_text_owner: Mapped[str | None] = mapped_column(Text, nullable=True)

    button_labels: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        default=dict,
        nullable=False,
    )
    menu_client: Mapped[list] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        default=list,
        nullable=False,
    )
    menu_staff: Mapped[list] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        default=list,
        nullable=False,
    )
    menu_owner: Mapped[list] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        default=list,
        nullable=False,
    )
    ui_theme: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        default=dict,
        nullable=False,
    )
    ai_settings: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        default=dict,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    tenant: Mapped["Tenant"] = relationship(
        "Tenant",
        back_populates="settings",
    )