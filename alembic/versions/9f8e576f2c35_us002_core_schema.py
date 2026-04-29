"""us002 core schema

Revision ID: 9f8e576f2c35
Revises: ab5d0b8b015c
Create Date: 2026-04-28 22:53:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9f8e576f2c35"
down_revision: str | Sequence[str] | None = "ab5d0b8b015c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


order_status_enum = postgresql.ENUM(
    "pending",
    "confirmed",
    "preparing",
    "ready",
    "delivered",
    "cancelled",
    name="orderstatus",
    create_type=False,
)
order_intent_enum = postgresql.ENUM(
    "ORDER",
    "CANCEL",
    "QUESTION",
    "OTHER",
    name="orderintent",
    create_type=False,
)
payment_status_enum = postgresql.ENUM(
    "unpaid",
    "paid",
    name="paymentstatus",
    create_type=False,
)


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    order_status_enum.create(op.get_bind(), checkfirst=True)
    order_intent_enum.create(op.get_bind(), checkfirst=True)
    payment_status_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "customers",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("zalo_user_id", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=False),
        sa.Column("phone", sa.String(length=15), nullable=True),
        sa.Column("default_address", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("zalo_user_id", name="uq_customers_zalo_user_id"),
    )

    op.create_table(
        "menu_items",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("price_vnd", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "daily_menu",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("menu_date", sa.Date(), nullable=False),
        sa.Column("menu_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("quantity_limit", sa.Integer(), nullable=False),
        sa.Column(
            "quantity_sold",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "is_available",
            sa.Boolean(),
            sa.Computed("quantity_sold < quantity_limit", persisted=True),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["menu_item_id"], ["menu_items.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_daily_menu_menu_date", "daily_menu", ["menu_date"], unique=False
    )

    op.create_table(
        "orders",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", order_status_enum, nullable=False),
        sa.Column("intent", order_intent_enum, nullable=False),
        sa.Column("delivery_address", sa.Text(), nullable=True),
        sa.Column(
            "payment_status",
            payment_status_enum,
            nullable=False,
            server_default=sa.text("'unpaid'"),
        ),
        sa.Column("raw_message", sa.Text(), nullable=False),
        sa.Column("zalo_message_id", sa.String(length=64), nullable=True),
        sa.Column(
            "llm_raw_response", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("llm_confidence", sa.Float(), nullable=True),
        sa.Column(
            "needs_review",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("llm_latency_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("zalo_message_id", name="uq_orders_zalo_message_id"),
    )
    op.create_index("ix_orders_created_at", "orders", ["created_at"], unique=False)
    op.execute(
        "CREATE INDEX ix_orders_created_at_date ON orders (((created_at AT TIME ZONE 'UTC')::date))"
    )

    op.create_table(
        "order_items",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("menu_item_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("raw_item_name", sa.String(length=100), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price_vnd", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.CheckConstraint("quantity > 0", name="ck_order_items_quantity_positive"),
        sa.ForeignKeyConstraint(["menu_item_id"], ["menu_items.id"]),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_order_items_order_id", "order_items", ["order_id"], unique=False
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION set_orders_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_orders_set_updated_at
        BEFORE UPDATE ON orders
        FOR EACH ROW
        EXECUTE FUNCTION set_orders_updated_at();
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TRIGGER IF EXISTS trg_orders_set_updated_at ON orders")
    op.execute("DROP FUNCTION IF EXISTS set_orders_updated_at()")

    op.drop_index("ix_order_items_order_id", table_name="order_items")
    op.drop_table("order_items")

    op.drop_index("ix_orders_created_at_date", table_name="orders")
    op.drop_index("ix_orders_created_at", table_name="orders")
    op.drop_table("orders")

    op.drop_index("ix_daily_menu_menu_date", table_name="daily_menu")
    op.drop_table("daily_menu")

    op.drop_table("menu_items")
    op.drop_table("customers")

    payment_status_enum.drop(op.get_bind(), checkfirst=True)
    order_intent_enum.drop(op.get_bind(), checkfirst=True)
    order_status_enum.drop(op.get_bind(), checkfirst=True)
