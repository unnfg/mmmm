"""
Table hierarchy:
    customers           — one row per unique (platform, platform_user_id) pair
    inbound_messages    — raw log of every incoming message from any platform
    menu_items          — master list of dishes (never deleted, only deactivated)
    daily_menu          — which items are available on a given date, with quantity caps
    orders              — confirmed food orders only (no QUESTION / OTHER noise)
    order_items         — individual line items within an order
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
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
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlmodel import Field, Relationship, SQLModel

# ─────────────────────────────────────────────────────────────────────────────
# ENUMS
#
# Using StrEnum so values serialize to plain strings in JSON / DB columns,
# making them readable without an extra lookup table.
# ─────────────────────────────────────────────────────────────────────────────


class MessagePlatform(StrEnum):
    """Messaging platform that sent the inbound message.

    Adding a new platform only requires a new enum value here —
    no schema changes, no new columns, no new tables.
    """

    ZALO = "zalo"


class MessageIntent(StrEnum):
    """LLM classification result for an inbound message.

    Intentionally lives on InboundMessage, NOT on Order.
    The Order table is semantically pure: every row there is a real food order.
    QUESTION and OTHER rows never cross the boundary into orders.
    """

    ORDER = "ORDER"  # customer is placing a food order
    CANCEL = "CANCEL"  # customer wants to cancel an existing order
    QUESTION = "QUESTION"  # customer is asking something (e.g. "what's on the menu?")
    OTHER = "OTHER"  # anything else (greetings, spam, unrecognised)


class OrderStatus(StrEnum):
    """Lifecycle states of a food order.

    Each transition should emit a WebSocket event to the dashboard.
        pending     → confirmed  : owner (or auto) confirms the order is valid
        confirmed   → preparing  : kitchen starts cooking
        preparing   → ready      : food is ready for pickup/delivery
        ready       → delivered  : delivery completed
        any state   → cancelled  : order was cancelled by customer or owner
    """

    PENDING = "pending"
    CONFIRMED = "confirmed"
    PREPARING = "preparing"
    READY = "ready"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


class PaymentStatus(StrEnum):
    """Payment state, used for end-of-day reconciliation."""

    UNPAID = "unpaid"
    PAID = "paid"


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
    # ID and create_at are generated only in Python.
    # If inserting directly using SQL (not through the application) → no value incorrect design
    id: uuid.UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=text("gen_random_uuid()"),
        )
    )
    hashed_password: str
    created_at: datetime = Field(
        sa_type=Column(
            DateTime(timezone=True), nullable=False, server_default=text("now()")
        )  # type: ignore
    )


# ─────────────────────────────────────────────────────────────────────────────
# CUSTOMERS
# ─────────────────────────────────────────────────────────────────────────────


class Customer(SQLModel, table=True):
    """A person who has sent at least one message through any supported platform.

    One physical person may have multiple rows here — one per platform account.
    This is intentional for MVP simplicity.

    V2 identity-merging strategy (when needed):
        Add a nullable `canonical_customer_id UUID` FK pointing to a "master" row.
        Existing data stays untouched; merge logic is purely additive.
    """

    __tablename__ = "customers"
    __table_args__ = (
        # A platform_user_id is unique within its platform, but two different
        # platforms can have colliding IDs (e.g. Zalo "123" ≠ Telegram "123").
        UniqueConstraint(
            "platform_user_id",
            "platform",
            name="uq_customers_platform_user",
        ),
    )

    id: uuid.UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            # Generate UUID at the DB level so it works even on direct SQL inserts.
            server_default=text("gen_random_uuid()"),
        )
    )
    # The user's ID string as issued by the platform (e.g. Zalo's "user_id" field).
    platform_user_id: str = Field(max_length=128, nullable=False)
    platform: MessagePlatform = Field(max_length=20, nullable=False)
    display_name: str = Field(max_length=100, nullable=False)
    # Phone is optional — not all platforms expose it.
    phone: str | None = Field(default=None, max_length=15)
    # Saved delivery address to pre-fill on the next order.
    default_address: str | None = Field(default=None, sa_type=Text)
    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=text("now()"),
        )
    )

    inbound_messages: list[InboundMessage] = Relationship(back_populates="customer")
    orders: list[Order] = Relationship(back_populates="customer")


# ─────────────────────────────────────────────────────────────────────────────
# INBOUND MESSAGES
# ─────────────────────────────────────────────────────────────────────────────


class InboundMessage(SQLModel, table=True):
    """Immutable log of every message received from any platform.

    Design principle: write-once, never delete.
    This table is the source of truth for the raw input side of the system.

    Separation of concerns:
        - All LLM metadata (confidence, raw response, latency) lives here,
          not on the Order, because they describe the *classification act*,
          not the order itself.
        - intent lives here for the same reason: it classifies the message,
          it does not describe the order.
        - QUESTION and OTHER rows exist only here; they never produce an Order row.

    Idempotency:
        The composite unique constraint on (platform, platform_message_id) is the
        deduplication key. The worker checks this before enqueuing, so even if
        Zalo retries the webhook the DB rejects the duplicate at constraint level.
    """

    __tablename__ = "inbound_messages"
    __table_args__ = (
        # Idempotency key — same platform + same message ID must not be processed twice.
        UniqueConstraint(
            "platform",
            "platform_message_id",
            name="uq_inbound_messages_platform_msg",
        ),
        Index("ix_inbound_messages_customer_id", "customer_id"),
        Index("ix_inbound_messages_created_at", "created_at"),
        # Filtering unprocessed messages is a hot path for the worker.
        Index(
            "ix_inbound_messages_processed_at_null",
            "processed_at",
            postgresql_where=text("processed_at IS NULL"),
        ),
        CheckConstraint(
            "llm_confidence IS NULL OR (llm_confidence >= 0 AND llm_confidence <= 1)",
            name="ck_inbound_messages_llm_confidence_range",
        ),
        CheckConstraint(
            "llm_latency_ms IS NULL OR llm_latency_ms >= 0",
            name="ck_inbound_messages_llm_latency_non_negative",
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
            PGUUID(as_uuid=True),
            ForeignKey("customers.id"),
            nullable=False,
        )
    )

    # ── Platform identity ────────────────────────────────────────────────────
    platform: MessagePlatform = Field(max_length=20, nullable=False)
    # The message ID issued by the platform. Used only for deduplication.
    platform_message_id: str = Field(max_length=128, nullable=False)

    # ── Raw content ──────────────────────────────────────────────────────────
    # Never overwrite this. It is the only ground truth we have about
    # what the customer actually typed.
    raw_content: str = Field(sa_type=Text, nullable=False)

    # ── LLM classification ───────────────────────────────────────────────────
    # All fields below are NULL until the worker processes this message.

    # null: message is still in the queue, not yet classified
    # value: classification is done; see processed_at for when
    intent: MessageIntent | None = Field(default=None, max_length=20)

    # 0.0 - 1.0. Values below 0.8 trigger needs_review = true on the Order.
    llm_confidence: float | None = Field(default=None)

    # Full JSON blob returned by the LLM. Kept for debugging when AI is wrong.
    # sa_column required because JSONB is a PostgreSQL-specific type that
    # SQLModel's Field() does not natively understand.
    llm_raw_response: dict | list | None = Field(
        default=None,
        sa_column=Column(JSONB, nullable=True),
    )

    # Wall-clock time the LLM API call took. Used to monitor latency over time.
    llm_latency_ms: int | None = Field(default=None)

    # ── Processing state ─────────────────────────────────────────────────────
    # NULL  = message is waiting in the queue or actively being processed.
    # value = worker finished (successfully or not — check the linked Order or logs).
    processed_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )

    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=text("now()"),
        )
    )

    customer: Customer = Relationship(back_populates="inbound_messages")
    # Populated only when intent = ORDER and the worker successfully created an order.
    order: Order | None = Relationship(back_populates="source_message")


# ─────────────────────────────────────────────────────────────────────────────
# MENU ITEMS
# ─────────────────────────────────────────────────────────────────────────────


class MenuItem(SQLModel, table=True):
    """Master catalogue of dishes. Rows are never hard-deleted.

    Soft-delete via is_active = false so that historical OrderItem records
    (which FK into this table) are never orphaned.

    These UUIDs are injected into the LLM system prompt so the model can
    select the correct id directly, eliminating fuzzy-matching in application code.
    """

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
    # Store price as integer VND to avoid floating-point rounding errors.
    price_vnd: int = Field(sa_type=Integer, nullable=False)
    description: str | None = Field(default=None, sa_type=Text)
    # False = dish is retired but must remain for historical order integrity.
    is_active: bool = Field(
        sa_column=Column(Boolean, nullable=False, server_default=text("true"))
    )

    daily_menus: list[DailyMenu] = Relationship(back_populates="menu_item")
    order_items: list[OrderItem] = Relationship(back_populates="menu_item")


# ─────────────────────────────────────────────────────────────────────────────
# DAILY MENU
# ─────────────────────────────────────────────────────────────────────────────


class DailyMenu(SQLModel, table=True):
    """Which dishes are offered on a specific date, with per-dish quantity caps.

    Separating this from MenuItem allows:
        - Same dish to appear across multiple days (with independent quantity caps).
        - Quantities to be tracked per-day without polluting the master catalogue.
        - The LLM prompt to be built from today's slice only (cheaper, more accurate).

    is_available is a DB-computed column — it is always consistent with
    quantity_sold and quantity_limit without any application-level bookkeeping.
    """

    __tablename__ = "daily_menu"
    __table_args__ = (
        # Prevent the same dish from appearing twice on the same day.
        UniqueConstraint(
            "menu_date",
            "menu_item_id",
            name="uq_daily_menu_date_item",
        ),
        Index("ix_daily_menu_date", "menu_date"),
        CheckConstraint(
            "quantity_limit >= 0", name="ck_daily_menu_quantity_limit_non_negative"
        ),
        CheckConstraint(
            "quantity_sold >= 0", name="ck_daily_menu_quantity_sold_non_negative"
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
    menu_date: date = Field(sa_type=Date, nullable=False)
    menu_item_id: uuid.UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            ForeignKey("menu_items.id"),
            nullable=False,
        )
    )
    quantity_limit: int = Field(sa_type=Integer, nullable=False)
    # Incremented (with SELECT FOR UPDATE) each time an order is confirmed,
    # to prevent overselling under concurrent load.
    quantity_sold: int = Field(
        sa_column=Column(Integer, nullable=False, server_default=text("0"))
    )
    # GENERATED ALWAYS — Postgres recomputes this on every write to the row.
    # persisted=True stores the result on disk so reads are O(1).
    # Application code must NEVER manually set this field.
    is_available: bool = Field(
        sa_column=Column(
            Boolean,
            Computed("quantity_sold < quantity_limit", persisted=True),
            nullable=False,
        )
    )

    menu_item: MenuItem = Relationship(back_populates="daily_menus")


# ─────────────────────────────────────────────────────────────────────────────
# ORDERS
# ─────────────────────────────────────────────────────────────────────────────


class Order(SQLModel, table=True):
    """A confirmed food order.

    Semantic contract: every row in this table is a real food order.
    There are no QUESTION, OTHER, or CANCEL rows here.
    No query on this table ever needs a WHERE intent = 'ORDER' guard.

    Audit trail:
        Raw message text and LLM metadata live on InboundMessage (via source_message).
        To answer "what did the customer type?", JOIN on source_message_id.
        This keeps orders clean while preserving full traceability.

    Human-in-the-loop:
        needs_review = true acts as a staging gate.
        Orders in this state are NOT counted toward revenue or dispatched for delivery
        until the owner explicitly confirms or edits them via the dashboard.
    """

    __tablename__ = "orders"
    __table_args__ = (
        Index("ix_orders_customer_id", "customer_id"),
        Index("ix_orders_created_at", "created_at"),
        # Partial index — only indexes the small subset of rows needing review.
        # Much cheaper than a full-table index when needs_review is rarely true.
        Index(
            "ix_orders_needs_review",
            "needs_review",
            postgresql_where=text("needs_review = true"),
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
            PGUUID(as_uuid=True),
            ForeignKey("customers.id"),
            nullable=False,
        )
    )
    # FK back to the message that created this order.
    # UNIQUE enforces the invariant: one message → at most one order.
    # The DB rejects a second order from the same message even if app logic has a bug.
    source_message_id: uuid.UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            ForeignKey("inbound_messages.id"),
            nullable=False,
            unique=True,
        )
    )
    status: OrderStatus = Field(max_length=20, nullable=False)
    # Null when the LLM could not parse an address (triggers needs_review = true).
    delivery_address: str | None = Field(default=None, sa_type=Text)
    payment_status: PaymentStatus = Field(
        default=PaymentStatus.UNPAID,
        nullable=False,
    )
    # True when the worker is not confident enough to auto-confirm.
    # Conditions: LLM confidence < 0.8, missing delivery_address,
    #             or any order_item has menu_item_id = null.
    # Dashboard highlights these rows in amber for the owner to verify.
    needs_review: bool = Field(
        sa_column=Column(Boolean, nullable=False, server_default=text("false"))
    )
    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=text("now()"),
        )
    )
    # Updated by a DB trigger (see ORDERS_SET_UPDATED_AT_*) on every row update.
    # Used in WebSocket payloads so the client knows the last-modified time.
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=text("now()"),
        )
    )

    customer: Customer = Relationship(back_populates="orders")
    source_message: InboundMessage = Relationship(back_populates="order")
    items: list[OrderItem] = Relationship(back_populates="order")


# ─────────────────────────────────────────────────────────────────────────────
# ORDER ITEMS
# ─────────────────────────────────────────────────────────────────────────────


class OrderItem(SQLModel, table=True):
    """A single line item (dish + quantity) within an Order.

    menu_item_id is intentionally nullable.
    When the LLM extracts a dish name that does not match any UUID in the
    day's menu, the worker stores the raw text in raw_item_name and sets
    order.needs_review = true. The owner then resolves the ambiguity manually.

    unit_price_vnd is a snapshot of the price at order time.
    It is deliberately decoupled from menu_items.price_vnd so that price
    changes do not retroactively alter historical order totals.
    """

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
        sa_column=Column(
            PGUUID(as_uuid=True),
            ForeignKey("orders.id"),
            nullable=False,
        )
    )
    # Null when the LLM could not match the dish to a known MenuItem UUID.
    # In that case raw_item_name contains what the customer typed (approx).
    menu_item_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            PGUUID(as_uuid=True),
            ForeignKey("menu_items.id"),
            nullable=True,
        ),
    )
    # The dish name as extracted by the LLM from the raw message.
    # Always populated, even when menu_item_id is resolved, for human readability.
    raw_item_name: str | None = Field(default=None, max_length=100)
    quantity: int = Field(sa_type=Integer, nullable=False)
    # Price snapshot — see docstring above.
    unit_price_vnd: int = Field(sa_type=Integer, nullable=False)
    # Free-text note from the customer, e.g. "less rice", "extra sauce".
    note: str | None = Field(default=None, sa_type=Text)

    order: Order = Relationship(back_populates="items")
    menu_item: MenuItem | None = Relationship(back_populates="order_items")


# ─────────────────────────────────────────────────────────────────────────────
# DDL — DB-level trigger for orders.updated_at
#
# Keeping the raw SQL here (rather than only in the migration) means:
#   1. The migration can import and reuse the exact same string.
#   2. It is obvious what DDL is associated with this model when reading models.py.
# ─────────────────────────────────────────────────────────────────────────────

ORDERS_SET_UPDATED_AT_FN = """
                           CREATE
                           OR REPLACE FUNCTION set_orders_updated_at()
RETURNS TRIGGER AS $$
                           BEGIN
    NEW.updated_at
                           = now();
                           RETURN NEW;
                           END;
$$
                           LANGUAGE plpgsql; \
                           """

ORDERS_SET_UPDATED_AT_TRIGGER = """
                                CREATE TRIGGER trg_orders_set_updated_at
                                    BEFORE UPDATE
                                    ON orders
                                    FOR EACH ROW EXECUTE FUNCTION set_orders_updated_at(); \
                                """

ORDERS_DROP_UPDATED_AT_TRIGGER = """
DROP TRIGGER IF EXISTS trg_orders_set_updated_at ON orders;
"""

ORDERS_DROP_UPDATED_AT_FN = """
DROP FUNCTION IF EXISTS set_orders_updated_at();
"""
