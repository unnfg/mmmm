import uuid
from datetime import UTC, date, datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlmodel import Field, Relationship, SQLModel


def get_datetime_utc() -> datetime:
    return datetime.now(UTC)


# Shared properties
class UserBase(SQLModel):
    phone_number: str = Field(unique=True, index=True, max_length=10, min_length=10)
    is_active: bool = True
    is_superuser: bool = False
    full_name: str | None = Field(default=None, max_length=255)


# Properties to receive via API on creation
class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=128)


# Properties to receive via API on update, all are optional
class UserUpdate(UserBase):
    phone_number: str | None = Field(default=None, min_length=10, max_length=10)  # type: ignore[assignment]
    password: str | None = Field(default=None, min_length=8, max_length=128)


class UserUpdateMe(SQLModel):
    full_name: str | None = Field(default=None, max_length=255)
    phone_number: str | None = Field(default=None, max_length=10, min_length=10)


class UpdatePassword(SQLModel):
    current_password: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


# Database model, database table inferred from class name
class User(UserBase, table=True):
    __tablename__ = "users"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    hashed_password: str
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class OrderStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    PREPARING = "preparing"
    READY = "ready"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


class OrderIntent(StrEnum):
    ORDER = "ORDER"
    CANCEL = "CANCEL"
    QUESTION = "QUESTION"
    OTHER = "OTHER"


class PaymentStatus(StrEnum):
    UNPAID = "unpaid"
    PAID = "paid"


class Customer(SQLModel, table=True):
    __tablename__ = "customers"

    id: uuid.UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=text("gen_random_uuid()"),
        )
    )
    zalo_user_id: str = Field(max_length=64, unique=True, nullable=False)
    display_name: str = Field(max_length=100, nullable=False)
    phone: str | None = Field(default=None, max_length=15)
    default_address: str | None = Field(default=None, sa_type=Text)
    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=text("now()")
        )
    )

    orders: list[Order] = Relationship(back_populates="customer")


class MenuItem(SQLModel, table=True):
    __tablename__ = "menu_items"

    id: uuid.UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=text("gen_random_uuid()"),
        )
    )
    name: str = Field(max_length=100, nullable=False)
    price_vnd: int = Field(sa_type=Integer, nullable=False)
    description: str | None = Field(default=None, sa_type=Text)
    is_active: bool = Field(
        sa_column=Column(Boolean, nullable=False, server_default=text("true"))
    )

    daily_menus: list[DailyMenu] = Relationship(back_populates="menu_item")
    order_items: list[OrderItem] = Relationship(back_populates="menu_item")


class DailyMenu(SQLModel, table=True):
    __tablename__ = "daily_menu"
    __table_args__ = (Index("ix_daily_menu_menu_date", "menu_date"),)

    id: uuid.UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=text("gen_random_uuid()"),
        )
    )
    menu_date: date = Field(sa_type=Date, nullable=False)
    menu_item_id: uuid.UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True), ForeignKey("menu_items.id"), nullable=False
        ),
    )
    quantity_limit: int = Field(sa_type=Integer, nullable=False)
    quantity_sold: int = Field(
        sa_column=Column(Integer, nullable=False, server_default=text("0"))
    )
    is_available: bool = Field(
        sa_column=Column(
            Boolean,
            Computed("quantity_sold < quantity_limit", persisted=True),
            nullable=False,
        )
    )

    menu_item: MenuItem = Relationship(back_populates="daily_menus")


class Order(SQLModel, table=True):
    __tablename__ = "orders"
    __table_args__ = (
        Index("ix_orders_created_at", "created_at"),
        Index(
            "ix_orders_created_at_date", text("((created_at AT TIME ZONE 'UTC')::date)")
        ),
    )

    id: uuid.UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=text("gen_random_uuid()"),
        )
    )
    customer_id: uuid.UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True), ForeignKey("customers.id"), nullable=False
        ),
    )
    status: OrderStatus = Field(max_length=20, nullable=False)
    intent: OrderIntent = Field(max_length=20, nullable=False)
    delivery_address: str | None = Field(default=None, sa_type=Text)
    payment_status: PaymentStatus = Field(
        default=PaymentStatus.UNPAID,
        max_length=10,
        nullable=False,
    )
    raw_message: str = Field(sa_type=Text, nullable=False)
    zalo_message_id: str | None = Field(default=None, max_length=64, unique=True)
    llm_raw_response: dict | list | None = Field(
        default=None, sa_column=Column(JSONB, nullable=True)
    )
    llm_confidence: float | None = Field(default=None)
    needs_review: bool = Field(default=False, nullable=False)
    llm_latency_ms: int | None = Field(default=None)
    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=text("now()")
        )
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=text("now()")
        )
    )

    customer: Customer = Relationship(back_populates="orders")
    items: list[OrderItem] = Relationship(back_populates="order")


class OrderItem(SQLModel, table=True):
    __tablename__ = "order_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_order_items_quantity_positive"),
        Index("ix_order_items_order_id", "order_id"),
    )

    id: uuid.UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=text("gen_random_uuid()"),
        )
    )
    order_id: uuid.UUID = Field(
        sa_column=Column(PGUUID(as_uuid=True), ForeignKey("orders.id"), nullable=False),
    )
    menu_item_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            PGUUID(as_uuid=True), ForeignKey("menu_items.id"), nullable=True
        ),
    )
    raw_item_name: str | None = Field(default=None, max_length=100)
    quantity: int = Field(sa_type=Integer, nullable=False)
    unit_price_vnd: int = Field(sa_type=Integer, nullable=False)
    note: str | None = Field(default=None, sa_type=Text)

    order: Order = Relationship(back_populates="items")
    menu_item: MenuItem | None = Relationship(back_populates="order_items")


# DB-level trigger logic for orders.updated_at.
# Keep DDL here so migration can reuse exact SQL.
ORDERS_SET_UPDATED_AT_FN = """
CREATE OR REPLACE FUNCTION set_orders_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

ORDERS_SET_UPDATED_AT_TRIGGER = """
CREATE TRIGGER trg_orders_set_updated_at
BEFORE UPDATE ON orders
FOR EACH ROW
EXECUTE FUNCTION set_orders_updated_at();
"""

ORDERS_DROP_UPDATED_AT_TRIGGER = """
DROP TRIGGER IF EXISTS trg_orders_set_updated_at ON orders;
"""

ORDERS_DROP_UPDATED_AT_FN = """
DROP FUNCTION IF EXISTS set_orders_updated_at();
"""
