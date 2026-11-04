"""Synology DSM client wrapper for multi-NAS management."""

import asyncio
from typing import Any

import aiohttp
from synology_dsm import SynologyDSM

from .config import NasConfig
from .direct_client import DirectApiClient
from .session_retry import with_session_retry

STARTUP_WAIT_SECONDS = 60.0
STARTUP_WAIT_INTERVAL = 2.0


async def wait_for_host(
    host: str,
    port: int,
    timeout: float = STARTUP_WAIT_SECONDS,
    interval: float = STARTUP_WAIT_INTERVAL,
) -> bool:
    """Wait until a NAS accepts TCP connections; False if it never does.

    At boot this container can start before its network is routable, and
    ``SynologyClient.connect`` only logs in once, so a failed attempt left the
    NAS disconnected until the next restart. This probes the port instead of
    retrying the login, so bad credentials can't trip DSM's auto-block.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), interval
            )
            writer.close()
            await writer.wait_closed()
            return True
        except (OSError, asyncio.TimeoutError):
            if loop.time() >= deadline:
                return False
            await asyncio.sleep(interval)


class SessionRetryingSynologyDSM(SynologyDSM):
    """SynologyDSM that re-logins and retries once on an expired session.

    py-synologydsm-api's built-in ``_request`` retry only fires on error code
    119; DSM hands out 106 ("session timeout") for idle sessions, which
    otherwise failed every call until the process was restarted. This override
    funnels each request through :func:`with_session_retry`, so a dead session
    transparently self-heals with a fresh login — covering every tool that
    talks to the NAS through the py-synologydsm-api data modules.
    """

    async def _request(
        self,
        request_method: str,
        api: str,
        method: str,
        params: dict | None = None,
        retry_once: bool = True,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        # The library re-enters _request with retry_once=False for its own
        # second pass; in that case just delegate so we never nest retries.
        if not retry_once:
            return await super()._request(
                request_method, api, method, params, False, *args, **kwargs
            )

        async def _call() -> Any:
            # Pass retry_once=False so the library's own (119-only) retry is
            # disabled — with_session_retry owns all session-error recovery
            # (106/107/119) and performs a real re-login first.
            return await super(SessionRetryingSynologyDSM, self)._request(
                request_method, api, method, params, False, *args, **kwargs
            )

        async def _login() -> None:
            self._session_id = None
            self._syno_token = None
            await self.login()

        return await with_session_retry(_call, _login, api=api)


class SynologyClient:
    """Manages SynologyDSM connections to multiple NAS units."""

    def __init__(self) -> None:
        self._clients: dict[str, SynologyDSM] = {}
        self._configs: dict[str, NasConfig] = {}
        self._session: aiohttp.ClientSession | None = None
        self.direct: DirectApiClient | None = None

    async def connect(self, configs: list[NasConfig]) -> None:
        """Initialize connections to all configured NAS units."""
        self._session = aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(ssl=False)
        )
        for config in configs:
            self._configs[config.name] = config
            if not await wait_for_host(config.host, config.port):
                print(f"{config.name} ({config.host}:{config.port}) not reachable")
            api = SessionRetryingSynologyDSM(
                self._session,
                config.host,
                config.port,
                config.username,
                config.password,
                use_https=config.use_https,
            )
            try:
                await api.login()
                self._clients[config.name] = api
                print(f"Connected to {config.name} ({config.host})")
            except Exception as e:
                print(f"Failed to connect to {config.name} ({config.host}): {e}")

        # Direct API client for raw SYNO.* endpoints
        self.direct = DirectApiClient(self._session)
        for config in configs:
            try:
                await self.direct.connect(config)
                print(f"Direct API connected to {config.name} ({config.host})")
            except Exception as e:
                print(f"Direct API failed for {config.name} ({config.host}): {e}")

    async def disconnect(self) -> None:
        """Close all connections."""
        if self._session and not self._session.closed:
            await self._session.close()
        self._clients.clear()

    def get_client(self, name: str) -> SynologyDSM | None:
        """Get a specific NAS client by name."""
        return self._clients.get(name.lower())

    def get_clients(self, nas: str | None = None) -> dict[str, SynologyDSM]:
        """Get clients filtered by NAS name, or all if None."""
        if nas:
            name = nas.lower()
            client = self._clients.get(name)
            return {name: client} if client else {}
        return dict(self._clients)

    @property
    def names(self) -> list[str]:
        """List of configured NAS names."""
        return list(self._configs.keys())

    def is_connected(self, name: str) -> bool:
        """Check if a NAS is connected."""
        return name in self._clients
