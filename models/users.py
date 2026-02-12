from __future__ import annotations

from enum import Enum
from datetime import datetime

from sqlalchemy import String, Integer, DateTime, Enum as SQLEnum, BigInteger, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.db_manager import Base


class UserRole(Enum):
    """Роли пользователей."""
    CLIENT = "client"
    STAFF = "staff"
    OWNER = "owner"


def normalize_role(role: str | UserRole) -> str:
    """Return a stable string value for a role enum or string."""
    if isinstance(role, UserRole):
        return role.value
    return str(role)


class User(Base):
    """Модель пользователя."""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    
    role: Mapped[str] = mapped_column(
        SQLEnum(
            UserRole,
            values_callable=lambda enums: [e.value for e in enums],
            name="userrole",
        ),
        default=UserRole.CLIENT.value,
        nullable=False,
    )
    
    ai_quota: Mapped[int] = mapped_column(Integer, default=25, nullable=False)
    ai_bonus_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False
    )

    # Связи
    orders: Mapped[list["Order"]] = relationship(
        "Order",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    @property
    def full_name(self) -> str:
        """Полное имя пользователя."""
        parts = []
        if self.first_name:
            parts.append(self.first_name)
        if self.last_name:
            parts.append(self.last_name)
        return " ".join(parts) if parts else f"Пользователь {self.tg_id}"

    def __repr__(self) -> str:
        return f"<User(id={self.id}, tg_id={self.tg_id}, role={self.role})>"