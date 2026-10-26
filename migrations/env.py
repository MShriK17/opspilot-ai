"""Alembic environment. Migrations are plain SQL, so there is no ORM metadata."""
import os

from alembic import context
from sqlalchemy import create_engine, pool

url = os.environ.get("OPSPILOT_DATABASE_URL", "postgresql://opspilot:opspilot@localhost:5432/opspilot")
if url.startswith("postgresql://"):
    url = url.replace("postgresql://", "postgresql+psycopg2://", 1)

if context.is_offline_mode():
    raise RuntimeError("offline mode is not supported")

engine = create_engine(url, poolclass=pool.NullPool)
with engine.connect() as connection:
    context.configure(connection=connection, target_metadata=None)
    with context.begin_transaction():
        context.run_migrations()
