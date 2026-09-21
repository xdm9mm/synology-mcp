# Eddington fork extensions

This is a fork of [lefty3382/synology-mcp](https://github.com/lefty3382/synology-mcp)
(`upstream` remote) for Mark's personal Eddington home-lab project
(`eddington-shared/mcp/servers.md` in a sibling repo has the full evaluation that led
to forking this one instead of building from zero, or adopting
`vocweb/synology-mcp-server`, which turned out to be Office-Suite-only and unrelated
to this need).

## Why fork instead of just running upstream as-is

Upstream covers storage/system health, file browsing/management, and power — but has
no tools for **DNS Server** (zone/record management) or **Active Backup for Business**
(device/task/restore-point status, triggering a backup). Those two are the actual
motivating need: giving an agent the ability to manage `eddington.place`'s LAN DNS
records and check/trigger NAS backups, instead of walking through DSM's UI by hand
every time.

## What's added

- `synology_mcp/tools/dns_server.py` — `dns_list_zones`, `dns_list_records` (read
  tier), `dns_create_record`, `dns_delete_record` (write tier, confirm-gated).
- `synology_mcp/tools/active_backup.py` — `abb_list_devices`, `abb_get_task_status`,
  `abb_list_restore_points` (read tier), `abb_trigger_backup` (write tier,
  confirm-gated).
- Wired into `server.py` at the same tier boundaries as the existing file
  browsing/management tools.

## Status as of 2026-09-21: read tools VERIFIED, write tools still guesses

Deployed to `hServer-L1` (192.168.1.126:8485, `docker-compose.yaml` at this repo's
root, `.env` holds a dedicated `mcp-service` DSM account — admin-group membership,
narrowed via Application Privileges to deny AFP/FTP/File Station/SFTP/SMB/rsync).
Ran `discover_apis` against Vault, then tested every read call live and corrected the
tool code to match reality. What changed from the original draft:

| Tool | Original guess | Verified reality |
|---|---|---|
| `dns_list_records` | `SYNO.DNSServer.Zone.Master.Record` | `SYNO.DNSServer.Zone.Record`, needs **both** `domain_name` and `zone_name` params (same value) |
| record fields | `owner`/`type`/`data`/`ttl` | `rr_owner`/`rr_type`/`rr_info`/`rr_ttl` |
| `abb_list_devices` | `SYNO.ActiveBackup.Inventory` | `SYNO.ActiveBackup.Device` — `Inventory` returns an empty list even with devices enrolled (likely a pre-deployment discovery list, not the enrolled-device list) |
| `abb_get_task_status` | assumed a direct `SYNO.ActiveBackup.Task / get` by device_name | no such call exists; resolve `device_name` → `task_id` via `Task/list`'s nested `devices[].host_name`, then take the newest entry from `Version/list(task_id=...)` sorted by `time_end` |
| `abb_list_restore_points` | assumed `device_id` param | `Version/list` takes `task_id`, not `device_id` — same resolution step as above |
| device fields | invented names | real fields include credential-shaped ones (`agent_token`, `login_password`, `mssql_password`, `oracle_password`) — empty today, but the tool code now uses an explicit field allowlist so these can never leak through even if populated later |

All four read tools (`dns_list_zones`, `dns_list_records`, `abb_list_devices`,
`abb_get_task_status`, `abb_list_restore_points`) were called end-to-end through
FastMCP's actual tool registration (not just raw API probing) against live Vault data
and returned correct results — see the deployment session for full output, or rerun
yourself: `docker compose exec synology-mcp python -c "..."` invoking
`mcp.get_tool(name).run(args)`.

**Still unverified — do not trust without further testing:** `dns_create_record`,
`dns_delete_record`, and `abb_trigger_backup`. These are mutating calls; testing them
live would actually change the `eddington.place` DNS zone or kick off a real NAS
backup job, which wasn't done as a side effect of read-only discovery. Their method
names (`create`/`delete` on `SYNO.DNSServer.Zone.Record`, `backup_now` on
`SYNO.ActiveBackup.Task`) and param shapes are educated guesses extrapolated from the
verified read schema, not confirmed. The confirm-gate preview mode (returning a
warning without executing) was tested and works correctly — only the actual mutation
path is unverified. Before trusting these: test against a disposable record (e.g. a
throwaway name in a test zone, or accept the risk on a real record you can easily
re-add) and a device where an extra manual backup run is genuinely low-cost.

## Bonus finding from this deployment

`abb_list_devices` surfaced a 4th device, `HSERVER-W1` (192.168.1.125, Windows 11) —
this is the Windows Pro boot of the same physical hardware as `hServer-L1` (dual-boot
box, see `eddington-shared/data/devices.yaml`), whose IP wasn't previously recorded.
Worth backfilling into `devices.yaml`.
