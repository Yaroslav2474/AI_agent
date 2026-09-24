from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from src.models.database import Base
import os

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://rechkapesok:rechkapesok_password@localhost:5432/rechkapesok")

engine = create_async_engine(DATABASE_URL, echo=True)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def get_session():
    async with async_session() as session:
        yield session

__all__ = ["engine", "init_db", "get_session"]
