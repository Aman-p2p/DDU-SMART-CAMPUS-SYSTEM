"""Pytest configuration and test database fixtures.
Ensures tables and campus seed data are initialized before any tests run,
and test reservations are cleaned between runs.
"""
import pytest_asyncio
from sqlalchemy import text
from app.database import engine, Base, AsyncSessionLocal
from app.seed.campus_seed_data import seed_campus_data

@pytest_asyncio.fixture(scope="session", autouse=True)
async def initialize_test_database():
    """Initializes tables and seeds campus data once per test session."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
        
    async with AsyncSessionLocal() as session:
        await seed_campus_data(session)
        await session.execute(text("DELETE FROM reservations"))
        await session.commit()
        
    yield
