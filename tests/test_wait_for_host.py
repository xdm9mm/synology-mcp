"""Tests for the startup wait in ``synology_mcp.client.wait_for_host``.

Runnable two ways:
  * ``pytest`` (no async plugin required — each test wraps asyncio.run)
  * ``python tests/test_wait_for_host.py`` (self-contained runner)
"""

import asyncio
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from synology_mcp.client import wait_for_host  # noqa: E402

HOST = "127.0.0.1"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind((HOST, 0))
        return sock.getsockname()[1]


async def _noop_handler(reader, writer) -> None:
    writer.close()


def test_returns_true_when_port_is_open() -> None:
    async def run() -> bool:
        port = _free_port()
        server = await asyncio.start_server(_noop_handler, HOST, port)
        async with server:
            return await wait_for_host(HOST, port, timeout=1, interval=0.05)

    assert asyncio.run(run()) is True


def test_returns_false_when_port_stays_closed() -> None:
    result = asyncio.run(wait_for_host(HOST, _free_port(), timeout=0.2, interval=0.05))
    assert result is False


def test_waits_for_port_that_opens_later() -> None:
    async def run() -> bool:
        port = _free_port()
        waiter = asyncio.create_task(wait_for_host(HOST, port, timeout=3, interval=0.05))
        await asyncio.sleep(0.3)
        assert not waiter.done()
        server = await asyncio.start_server(_noop_handler, HOST, port)
        async with server:
            return await waiter

    assert asyncio.run(run()) is True


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
        print(f"ok  {test.__name__}")
    print(f"{len(tests)} passed")
