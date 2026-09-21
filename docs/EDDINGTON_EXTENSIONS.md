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
every time (see the `eddington_infrastructure.md` history around 2026-09-21 for the
concrete case — a manually-added DNS record that had a typo, and a new host,
`hServer-L1`, that needed Active Backup for Business enrollment).

## What's added

- `synology_mcp/tools/dns_server.py` — `dns_list_zones`, `dns_list_records` (read
  tier), `dns_create_record`, `dns_delete_record` (write tier, confirm-gated).
- `synology_mcp/tools/active_backup.py` — `abb_list_devices`, `abb_get_task_status`,
  `abb_list_restore_points` (read tier), `abb_trigger_backup` (write tier,
  confirm-gated).
- Wired into `server.py` at the same tier boundaries as the existing file
  browsing/management tools.

Both new files follow the exact request/response/error-handling shape already used in
`tools/diagnostic.py` (`DirectApiClient.call(api, method, version=N, **params)`, one
try/except per NAS connection, soft `{"error": ...}` returns) and the confirm-gated
mutation pattern in `tools/power.py`.

## Status: NOT VERIFIED — do not trust the endpoint names yet

Every `SYNO.DNSServer.*` and `SYNO.ActiveBackup.*` call in the two new files is a
**best-effort guess** based on Synology's public API naming convention, written
without a live NAS running either package in front of the author. Before trusting any
of this:

1. Deploy this fork (health tier first) against a NAS with DNS Server installed and
   at least one device enrolled in Active Backup for Business.
2. Run the existing `discover_apis` tool and grep its output for `DNSServer` and
   `ActiveBackup` to get the real API names, versions, and parameter shapes.
3. Cross-check against Synology's official "DNS Server API Guide" and "Active Backup
   for Business API Guide" PDFs if available.
4. Fix every `conn.call(...)` in both new files to match, delete this notice's
   "NOT VERIFIED" framing once done, and add real tests (`tests/`) mirroring
   `test_session_retry.py`'s style.

Until that verification pass happens, treat every tool in these two files as
**draft code that will likely return errors or wrong data**, not working software.
