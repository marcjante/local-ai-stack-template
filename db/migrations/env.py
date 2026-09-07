from logging.config import fileConfig
import os
import sys

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from db.db import DB_DSN  # noqa: E402


def _libpq_dsn_to_sqlalchemy_url(dsn: str) -> str:
    """
    db.DB_DSN está en formato libpq ('dbname=x user=y host=z port=w'),
    porque es lo que psycopg2.connect() acepta directamente. Alembic (vía
    SQLAlchemy) necesita una URL 'postgresql://user:pass@host:port/dbname'.
    Se traduce aquí para no duplicar la configuración de conexión en dos
    sitios — la fuente de verdad sigue siendo DATABASE_URL / db.DB_DSN.
    """
    if dsn.startswith("postgresql://") or dsn.startswith("postgres://"):
        return dsn
    parts = dict(p.split("=", 1) for p in dsn.split() if "=" in p)
    user = parts.get("user", "postgres")
    password = parts.get("password", "")
    host = parts.get("host", "127.0.0.1")
    port = parts.get("port", "5432")
    dbname = parts.get("dbname", "postgres")
    auth = f"{user}:{password}@" if password else f"{user}@"
    return f"postgresql://{auth}{host}:{port}/{dbname}"


# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config
config.set_main_option("sqlalchemy.url", _libpq_dsn_to_sqlalchemy_url(DB_DSN))

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
target_metadata = None

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
