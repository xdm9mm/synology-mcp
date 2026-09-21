"""Active Backup for Business tools (Eddington fork extension — see docs/EDDINGTON_EXTENSIONS.md).

Read tools are VERIFIED — tested live against Vault (Synology DS718+, DSM 7.3.2,
Active Backup for Business with MARK-PC/HLAPTOP/hLaptop enrolled) on 2026-09-21
via discover_apis + direct conn.call probing. Real API shape, not guesses:

- SYNO.ActiveBackup.Device / list (NOT .Inventory, which is unused/empty in
  this deployment — no params) -> {"devices": [...]}. Device objects also
  carry credential-shaped fields (agent_token, login_password, mssql_password,
  oracle_password) — empty for these DSM-agent-based devices, but NEVER pass
  the raw device dict through a tool response; only forward the explicit
  allowlist of fields below.
- SYNO.ActiveBackup.Task / list (no params) -> {"tasks": [...]}, each task has
  task_id, task_name, next_trigger_time, and a nested "devices" list (each
  with host_name) — this is how a device_name argument gets resolved to a
  task_id, there is no direct device-name-keyed status call.
- SYNO.ActiveBackup.Version / list (param: task_id, NOT device_id) ->
  {"total": N, "versions": [...]}, each version has version_id, folder_name,
  time_start, time_end (unix seconds), status (numeric — 3 observed for two
  known-good completed backups, exact enum not confirmed beyond that),
  verify_status (numeric — 6 observed, meaning not confirmed), used_size.
  Sorting by time_end descending gives the latest backup.
- SYNO.ActiveBackup.Inventory / list and SYNO.ActiveBackup.Overview / get and
  SYNO.ActiveBackup.Log / list were tried and are NOT the right calls for this
  (Inventory returned an empty list even with devices present — likely a
  pre-deployment VM/agentless discovery list, not enrolled devices; Overview
  and Log both returned error code 103 with the params tried).

Write tool (abb_trigger_backup) is STILL UNVERIFIED — "backup_now" as the
method name on SYNO.ActiveBackup.Task, taking task_id, is an educated guess
extrapolated from the verified Task schema, not tested live (a live test
would actually start a real backup job on the NAS).
"""

from fastmcp import FastMCP

from ..client import SynologyClient


async def _resolve_task_id(conn, device_name: str) -> tuple[int | None, str | None]:
    """Look up a device's task_id by matching host_name in Task/list's nested devices.

    Returns (task_id, error). VERIFIED 2026-09-21 — there is no direct
    device-name-keyed lookup; this two-step resolution (Task/list -> match
    host_name -> task_id) is the confirmed-working path.
    """
    try:
        data = await conn.call("SYNO.ActiveBackup.Task", "list", version=1)
    except Exception as e:
        return None, str(e)

    for task in data.get("tasks", []):
        for device in task.get("devices", []):
            if device.get("host_name", "").lower() == device_name.lower():
                return task.get("task_id"), None
    return None, f"No task found for device '{device_name}'"


def register_backup_read_tools(mcp: FastMCP, client: SynologyClient) -> None:
    """Read-only Active Backup for Business tools — inventory, task status, restore points. VERIFIED 2026-09-21."""

    @mcp.tool
    async def abb_list_devices(nas: str | None = None) -> dict:
        """List devices enrolled in Active Backup for Business.

        Args:
            nas: NAS name (e.g., 'vault'). If omitted, queries all.
        """
        if not client.direct:
            return {"error": "Direct API client not initialized"}

        results = {}
        for name, conn in client.direct.get_connections(nas).items():
            try:
                data = await conn.call(
                    "SYNO.ActiveBackup.Device",
                    "list",
                    version=1,
                )
                # Explicit allowlist — the raw device dict carries credential-
                # shaped fields (agent_token, *_password) that must never be
                # forwarded, even when empty today.
                devices = [
                    {
                        "device_id": d.get("device_id"),
                        "host_name": d.get("host_name"),
                        "host_ip": d.get("host_ip"),
                        "os_name": d.get("os_name"),
                        "task_count": d.get("task_count"),
                    }
                    for d in data.get("devices", [])
                ]
                results[name] = {"device_count": len(devices), "devices": devices}
            except Exception as e:
                results[name] = {"error": str(e)}
        return results

    @mcp.tool
    async def abb_get_task_status(nas: str, device_name: str) -> dict:
        """Get the latest backup status for one enrolled device.

        Resolves device_name to its task via Task/list, then reports the most
        recent entry from Version/list for that task (sorted by time_end).

        Args:
            nas: NAS name (e.g., 'vault'). Required.
            device_name: The device's host name as shown in Active Backup for
                         Business (e.g. 'MARK-PC', 'hServer-L1' once enrolled).
        """
        if not client.direct:
            return {"error": "Direct API client not initialized"}

        connections = client.direct.get_connections(nas)
        if not connections:
            return {"error": f"NAS '{nas}' not found or not connected"}

        name = nas.lower()
        conn = connections[name]

        task_id, err = await _resolve_task_id(conn, device_name)
        if task_id is None:
            return {"error": err, "nas": name, "device_name": device_name}

        try:
            vdata = await conn.call(
                "SYNO.ActiveBackup.Version",
                "list",
                version=1,
                task_id=task_id,
            )
            versions = sorted(
                vdata.get("versions", []), key=lambda v: v.get("time_end", 0), reverse=True
            )
            if not versions:
                return {
                    "nas": name,
                    "device_name": device_name,
                    "task_id": task_id,
                    "message": "Task exists but has no completed backup versions yet.",
                }
            latest = versions[0]
            return {
                "nas": name,
                "device_name": device_name,
                "task_id": task_id,
                "latest_version_id": latest.get("version_id"),
                "status": latest.get("status"),
                "verify_status": latest.get("verify_status"),
                "time_start": latest.get("time_start"),
                "time_end": latest.get("time_end"),
                "folder_name": latest.get("folder_name"),
            }
        except Exception as e:
            return {"error": str(e), "nas": name, "device_name": device_name, "task_id": task_id}

    @mcp.tool
    async def abb_list_restore_points(nas: str, device_name: str) -> dict:
        """List available restore points (backup versions) for one device.

        Resolves device_name to its task via Task/list, then lists all
        versions for that task.

        Args:
            nas: NAS name (e.g., 'vault'). Required.
            device_name: The device's host name as shown in Active Backup for
                         Business (e.g. 'MARK-PC', 'hServer-L1' once enrolled).
        """
        if not client.direct:
            return {"error": "Direct API client not initialized"}

        connections = client.direct.get_connections(nas)
        if not connections:
            return {"error": f"NAS '{nas}' not found or not connected"}

        name = nas.lower()
        conn = connections[name]

        task_id, err = await _resolve_task_id(conn, device_name)
        if task_id is None:
            return {"error": err, "nas": name, "device_name": device_name}

        try:
            data = await conn.call(
                "SYNO.ActiveBackup.Version",
                "list",
                version=1,
                task_id=task_id,
            )
            points = [
                {
                    "version_id": v.get("version_id"),
                    "folder_name": v.get("folder_name"),
                    "time_start": v.get("time_start"),
                    "time_end": v.get("time_end"),
                    "status": v.get("status"),
                    "verify_status": v.get("verify_status"),
                    "used_size": v.get("used_size"),
                }
                for v in data.get("versions", [])
            ]
            return {
                "nas": name,
                "device_name": device_name,
                "task_id": task_id,
                "restore_point_count": data.get("total", len(points)),
                "restore_points": points,
            }
        except Exception as e:
            return {"error": str(e), "nas": name, "device_name": device_name, "task_id": task_id}


def register_backup_write_tools(mcp: FastMCP, client: SynologyClient) -> None:
    """Mutating Active Backup for Business tools — trigger a backup (confirm-gated). UNVERIFIED."""

    @mcp.tool
    async def abb_trigger_backup(nas: str, device_name: str, confirm: bool = False) -> dict:
        """Trigger an immediate backup run for one enrolled device.

        STILL UNVERIFIED — see module docstring. The device_name->task_id
        resolution is confirmed-working (shared with the read tools above);
        "backup_now" as the run-now method name on SYNO.ActiveBackup.Task is
        an educated guess, not tested live (a live test would actually start
        a real backup job on the NAS). Mirrors the confirm-gated pattern used
        by shutdown_nas/reboot_nas in tools/power.py.

        Args:
            nas: NAS name (e.g., 'vault'). Required.
            device_name: The device's host name as shown in Active Backup for
                         Business (e.g. 'MARK-PC').
            confirm: Safety gate. Must be True to execute. When False,
                     returns a preview of what will happen.
        """
        if not client.direct:
            return {"error": "Direct API client not initialized"}

        connections = client.direct.get_connections(nas)
        if not connections:
            return {"error": f"NAS '{nas}' not found or not connected"}

        name = nas.lower()
        conn = connections[name]

        task_id, err = await _resolve_task_id(conn, device_name)
        if task_id is None:
            return {"error": err, "nas": name, "device_name": device_name}

        if not confirm:
            return {
                "preview": True,
                "action": "trigger_backup",
                "nas": name,
                "device_name": device_name,
                "task_id": task_id,
                "warning": (
                    f"This will start an immediate Active Backup for Business run for "
                    f"'{device_name}' (task_id={task_id}). It can be long-running and "
                    "resource-intensive on the NAS. Set confirm=True to proceed. "
                    "NOTE: the underlying API call is UNVERIFIED against a real DSM instance."
                ),
            }

        try:
            await conn.call(
                "SYNO.ActiveBackup.Task",
                "backup_now",
                version=1,
                task_id=task_id,
            )
            return {
                "success": True,
                "action": "trigger_backup",
                "nas": name,
                "device_name": device_name,
                "task_id": task_id,
                "message": f"Backup triggered for '{device_name}'.",
            }
        except Exception as e:
            return {"error": str(e), "nas": name, "device_name": device_name, "task_id": task_id}
