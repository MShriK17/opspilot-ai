"""Database access with a connection gate that can simulate pool exhaustion."""
import random
import threading
import time
from contextlib import contextmanager

from sqlalchemy import Column, DateTime, Float, Integer, String, create_engine, func
from sqlalchemy.orm import declarative_base, sessionmaker

from .chaos import chaos
from .config import settings

Base = declarative_base()


class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True)
    name = Column(String(80), nullable=False)
    price = Column(Float, nullable=False)


class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, nullable=False)
    quantity = Column(Integer, nullable=False)
    total = Column(Float, nullable=False)
    status = Column(String(20), nullable=False, default="paid")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class PoolTimeout(Exception):
    pass


class DatabaseUnavailable(Exception):
    pass


class ConnectionGate:
    """Counting gate in front of the DB. Its size is read at acquire time, so the
    chaos switch can shrink it live. Error text mimics SQLAlchemy's QueuePool."""

    def __init__(self, size_fn):
        self._size_fn = size_fn
        self._in_use = 0
        self._cv = threading.Condition()

    @property
    def in_use(self) -> int:
        return self._in_use

    def acquire(self, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        with self._cv:
            while self._in_use >= self._size_fn():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise PoolTimeout(
                        f"QueuePool limit of size {self._size_fn()} overflow 0 reached, "
                        f"connection timed out, timeout {timeout:.2f}"
                    )
                self._cv.wait(remaining)
            self._in_use += 1

    def release(self) -> None:
        with self._cv:
            self._in_use -= 1
            self._cv.notify()


gate = ConnectionGate(chaos.pool_size)

_is_sqlite = settings.database_url.startswith("sqlite")
engine = create_engine(
    settings.database_url,
    **(
        {"connect_args": {"check_same_thread": False}}
        if _is_sqlite
        else {"pool_size": 10, "max_overflow": 0, "pool_pre_ping": True}
    ),
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        if s.query(Product).count() == 0:
            s.add_all(
                [
                    Product(name=n, price=p)
                    for n, p in [
                        ("Notebook", 120.0),
                        ("Pen set", 80.0),
                        ("Backpack", 899.0),
                        ("Desk lamp", 450.0),
                        ("Headphones", 1599.0),
                    ]
                ]
            )
            s.commit()


@contextmanager
def db_session():
    if chaos.is_active("bad_env_var"):
        raise DatabaseUnavailable(
            "could not translate host name 'db-prod-typo' to address: Name or service not known"
        )
    gate.acquire(timeout=settings.pool_timeout_s)
    try:
        with SessionLocal() as session:
            if chaos.is_active("db_pool_exhausted"):
                time.sleep(random.uniform(0.8, 1.5))  # slow query holds the connection
            yield session
    finally:
        gate.release()
