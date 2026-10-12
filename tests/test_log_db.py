"""Event-log chain against a real Postgres. Skipped unless DAO_TEST_DATABASE_URL is set, e.g.
DAO_TEST_DATABASE_URL=postgresql+asyncpg://dao:pw@db:5432/dao_test (a scratch database; it is wiped)."""

import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from dao.db import Base
from dao.log import EventLog
from dao.models import LogHead  # noqa: F401  (registers the table on Base.metadata)
from dao.signer import Signer
from xe.keys import KeyPair

URL = os.environ.get("DAO_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="DAO_TEST_DATABASE_URL not set")


@pytest.fixture
async def db():
    eng = create_async_engine(URL)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("INSERT INTO log_head (id, index, hash) VALUES (1, -1, repeat('0', 64))"))
    sm = async_sessionmaker(eng, expire_on_commit=False)
    async with sm() as s:
        yield s
    await eng.dispose()


def _signer():
    kp = KeyPair.generate()
    return Signer({"harness": kp}, {"harness": {"event.sign"}})


async def test_append_chain_and_verify(db):
    log = EventLog(_signer())
    for i in range(5):
        await log.append(db, "test", "harness", {"i": i})
    await db.commit()
    res = await EventLog.verify(db)
    assert res["ok"] and res["count"] == 5
    head = await EventLog.head(db)
    assert head.index == 4


async def test_tamper_is_detected(db):
    log = EventLog(_signer())
    for i in range(3):
        await log.append(db, "test", "harness", {"i": i})
    await db.commit()
    await db.execute(text("UPDATE events SET payload = '{\"i\": 99}'::jsonb WHERE index = 1"))
    await db.commit()
    res = await EventLog.verify(db)
    assert not res["ok"] and "hash mismatch at 1" in res["first_error"]
