"""Guards for the autouse isolation in conftest.py."""
from __future__ import annotations

import os

import httpx
import pytest

from tests.conftest import NetworkBlocked


def test_real_http_is_blocked():
    with pytest.raises(NetworkBlocked):
        httpx.get("https://api.stlouisfed.org/")


async def _async_get():
    async with httpx.AsyncClient() as client:
        await client.get("https://api.stlouisfed.org/")


def test_real_async_http_is_blocked():
    import asyncio
    with pytest.raises(NetworkBlocked):
        asyncio.run(_async_get())


def test_each_test_gets_its_own_data_dir(tmp_path):
    assert os.environ["POE_DATA_DIR"].startswith(str(tmp_path))
    assert os.environ["EVIDENCE_SCHEDULER_ENABLED"] == "false"
    assert os.environ["POE_LOAD_DOTENV"] == "0"
