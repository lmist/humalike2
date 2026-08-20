"""Alembic environment for the Humalike API recreation.

Target metadata is `humalike.db.Base.metadata` with `humalike.storage` imported
so every model in the phase 0-8 table set is registered before autogenerate or
`--sql` rendering runs (spec/07 §Delivery discipline: each phase ships
migrations).

The database URL resolution order is:

1. ``alembic -x url=...`` (one-off target, used by the scratch verification),
2. ``HUMALIKE_DATABASE_URL`` via ``humalike.config.settings`` (what the service
   itself uses),
3. ``sqlalchemy.url`` in alembic.ini (left blank on purpose).
"""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

_HERE = os.path.dirname(os.path.abspath(__file__))
_SERVICE_ROOT = os.path.dirname(_HERE)
if _SERVICE_ROOT not in sys.path:
    sys.path.insert(0, _SERVICE_ROOT)

from humalike import storage  # noqa: E402,F401  (registers every model)
from humalike.config import settings  # noqa: E402
from humalike.db import Base  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def database_url() -> str:
    override = context.get_x_argument(as_dictionary=True).get("url")
    if override:
        return override
    if config.get_main_option("sqlalchemy.url"):
        return config.get_main_option("sqlalchemy.url")
    return settings.database_url


def run_migrations_offline() -> None:
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = database_url()
    connectable = engine_from_config(
        section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            # SQLite cannot ALTER most columns; batch mode keeps future
            # per-phase migrations reversible on the default deployment.
            render_as_batch=connection.dialect.name == "sqlite",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
