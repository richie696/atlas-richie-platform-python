"""Shared fixtures: an Alembic script tree and a PostgreSQL availability gate."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

PG_URL = os.environ.get(
    "ATLAS_RICHIE_PERSISTENCE_PG_TEST_URL",
    "postgresql://postgres@127.0.0.1:15432/vector_tests",
)

_ALEMBIC_ENV = '''
from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config
connectable = engine_from_config(
    config.get_section(config.config_ini_section),
    prefix="sqlalchemy.",
    poolclass=pool.NullPool,
)
with connectable.connect() as connection:
    context.configure(connection=connection, target_metadata=None)
    with context.begin_transaction():
        context.run_migrations()
'''

_ALEMBIC_MAKO = '''
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
"""
from alembic import op
import sqlalchemy as sa

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
'''

_REVISION = '''
"""create widgets

Revision ID: 0001
Revises:
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("widgets", sa.Column("id", sa.Integer, primary_key=True),
                    sa.Column("name", sa.String(32)))


def downgrade() -> None:
    op.drop_table("widgets")
'''



def _pg_ready(url: str) -> bool:
    try:
        from sqlalchemy import create_engine, text

        engine = create_engine(url, pool_pre_ping=True)
        try:
            with engine.connect() as connection:
                return bool(connection.execute(text("SELECT 1")).scalar())
        finally:
            engine.dispose()
    except Exception:  # noqa: BLE001 — 不可达或需要凭证均视为不可用
        return False


@pytest.fixture(scope="module")
def requires_pg() -> str:
    if not _pg_ready(PG_URL):
        pytest.skip(f"PostgreSQL not reachable at {PG_URL}")
    return PG_URL


@pytest.fixture
def script_location(tmp_path: Path) -> str:
    root = tmp_path / "migrations"
    (root / "versions").mkdir(parents=True)
    (root / "env.py").write_text(_ALEMBIC_ENV)
    (root / "script.py.mako").write_text(_ALEMBIC_MAKO)
    (root / "versions" / "0001_widgets.py").write_text(_REVISION)
    return str(root)
