"""
Veritabanı BAĞLANTI yönetimi — async engine, session factory, init/dependency.

Bu modül SADECE bağlantı katmanını içerir (create_async_engine, async_session,
init_db, get_db). Tablo/model tanımları için bkz. models/database.py.

İki dosya da `database.py` adını taşır ama sorumlulukları ayrıdır:
 models.database = ŞEMA (Base + tablolar), services.database = BAĞLANTI (engine/session).
"""
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from config import get_settings
from models.database import Base

settings = get_settings()

_is_sqlite = settings.database_url.startswith("sqlite")

_engine_kwargs = {
    "echo": False,
    "future": True,
    "pool_pre_ping": True,
}

if _is_sqlite:
    _engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    _engine_kwargs["pool_size"] = 5
    _engine_kwargs["max_overflow"] = 5
    _engine_kwargs["pool_recycle"] = 3600

engine = create_async_engine(settings.database_url, **_engine_kwargs)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db():
    """Veritabanı tablolarını oluşturur."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db() -> AsyncSession:
    """FastAPI dependency: async DB session."""
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()
