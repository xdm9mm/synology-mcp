# Changelog

All notable changes to the Synology MCP Server are documented in this file.

## [3.0.2] - 2026-11-03

### Fixed
- **NAS connections survive host reboots.** The container could start before
  its network was routable, the single login attempt failed, and the NAS stayed
  disconnected until a manual restart. `SynologyClient.connect` now waits up to
  60 seconds for the DSM port before logging in.

## [3.0.1] - 2026-06-16

### Fixed
- **Expired DSM sessions now self-heal.** DSM invalidates idle session IDs and
  returns error code 106 ("session timeout"), but both py-synologydsm-api's own
  `_request` retry and `DirectApiClient.call` only retried on code 119 — so once
  an idle session expired, every health/storage call failed (`Session timeout`
  then `Not logged in. You have to do login() first.`) until the container was
  manually restarted. Both layers now re-login and retry once on codes 106/107/119.
- New `session_retry` module centralises session-error detection and the
  re-login/retry helper; `client.py` routes the py-synologydsm-api data path
  through a `SessionRetryingSynologyDSM` subclass (covers all health tools with
  no per-tool changes).

### Changed
- Pinned `py-synologydsm-api==2.7.3` (the subclass overrides the library's
  private `_request`; the pin keeps that override stable across rebuilds).

### Added
- `tests/test_session_retry.py` and a CI test job (gates the image build).

### Note
- This is the first published image to include the v2.1.0 power tools
  (`shutdown_nas` / `reboot_nas`): the v3.0.0 tag was mistakenly applied to an
  earlier commit, so the v2.1.0 work was committed to `main` but never built.
  v3.0.1 catches the release line up to `main`.

## [2.1.0] - 2026-03-18

### Added
- `shutdown_nas` — gracefully shut down a NAS unit (write tier, confirm-gated)
- `reboot_nas` — gracefully reboot a NAS unit (write tier, confirm-gated)
- Both tools use `SYNO.Core.System` API with a `confirm=True` safety gate
- Total tool count at write tier: 35 → 37

## [2.0.0] - 2026-03-06

### Added
- `DirectApiClient` — lightweight HTTP client for raw SYNO.* API calls with session management and 30s response caching
- `discover_apis` — list all available API endpoints on a NAS
- `get_disk_details` — full disk hardware info (model, serial, vendor, firmware, role, tray status)
- `get_ssd_cache` — SSD cache pool status and member disk health
- `get_storage_pool_members` — per-pool disk membership with RAID details
- `get_nfs_exports` — NFS shared folders with allowed hosts and permissions
- `get_services_status` — running state of NFS, SMB, SSH, rsync, SNMP
- `get_ups_status` — UPS model, battery charge, runtime, NUT config
- `get_hardware_info` — fan speeds, power recovery, beep control
- `get_recent_logs` — system logs with severity/keyword filtering
- `get_notifications` — DSM notification config and alert history
- `get_active_connections` — connected SMB/NFS/FTP clients
- `get_users` — local user accounts and group membership
- `get_update_status` — available DSM updates and current version

### Changed
- `get_health_summary` — enhanced with SSD cache, UPS, and NFS service alerts via direct API
- Tool count: 10 → 23 (health tier)

## [1.0.1] - 2026-03-05

### Fixed
- Added `PYTHONUNBUFFERED=1` to Dockerfile so NAS connection logs are visible in `docker compose logs`

### Changed
- Renamed `mcp-readonly` to `mcp-service` in README and `.env.example` — the server supports write tier, so the old name was misleading

## [1.0.0] - 2026-03-05

### Added
- Initial release
- FastMCP server with native Streamable HTTP transport (port 8485)
- Multi-NAS support via `SYNOLOGY_<NAME>_HOST` environment variable discovery
- Three permission tiers controlled by `MCP_PERMISSION_TIER` env var:
  - `health` (default): 10 tools — system info, volumes, disks, SMART, shares, network, utilization, health summary
  - `read`: health + 3 tools — list directory, get file info, list shared folders
  - `write`: health + read + 2 tools — upload file, delete file
- Docker image published to GHCR (`ghcr.io/lefty3382/synology-mcp`)
- GitHub Actions workflow for automated Docker image builds on tag push
