"""
Veritabanı bağlantı yönetimi.
"""
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from config import get_settings
from models.database import Base

settings = get_settings()

engine = create_async_engine(settings.database_url, echo=False, future=True)
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
