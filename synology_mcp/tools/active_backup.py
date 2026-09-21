"""Active Backup for Business tools (Eddington fork extension — see docs/EDDINGTON_EXTENSIONS.md).

UNVERIFIED ENDPOINT NAMES. The SYNO.ActiveBackup.* calls below are a
best-effort guess based on Synology's public API naming convention, not
confirmed against a real DSM instance or Synology's official "Active Backup
for Business API Guide" PDF. Before relying on these:

1. Deploy this fork against a NAS running Active Backup for Business with at
   least one device (e.g. hServer-L1, once enrolled — see
   eddington-infra/docs/HSERVER_L1_ABB_AGENT_HANDOFF.md) already backed up.
2. Run the existing `discover_apis` tool (tools/diagnostic.py) and grep its
   output for "ActiveBackup" to get the real API names, versions, and CGI
   paths.
3. Correct every `conn.call(...)` below to match, then remove this notice.

Modeled on the request/response/error-handling shape already used throughout
tools/diagnostic.py, and the confirm-gated mutation pattern in tools/power.py.
"""

from fastmcp import FastMCP

from ..client import SynologyClient


def register_backup_read_tools(mcp: FastMCP, client: SynologyClient) -> None:
    """Read-only Active Backup for Business tools — inventory, task status, restore points."""

    @mcp.tool
    async def abb_list_devices(nas: str | None = None) -> dict:
        """List devices enrolled in Active Backup for Business.

        UNVERIFIED — see module docstring. Expected to map to something like
        SYNO.ActiveBackup.Inventory / list, covering Physical Server (Windows/
        Linux), PC, VM, and file-server device types.

        Args:
            nas: NAS name (e.g., 'vault'). If omitted, queries all.
        """
        if not client.direct:
            return {"error": "Direct API client not initialized"}

        results = {}
        for name, conn in client.direct.get_connections(nas).items():
            try:
                data = await conn.call(
                    "SYNO.ActiveBackup.Inventory",
                    "list",
                    version=1,
                )
                devices = [
                    {
                        "name": d.get("device_name") or d.get("name"),
                        "type": d.get("device_type") or d.get("type"),
                        "os": d.get("os_name"),
                        "last_backup_result": d.get("last_bkp_result") or d.get("status"),
                        "last_backup_time": d.get("last_bkp_time"),
                    }
                    for d in data.get("devices", data.get("items", []))
                ]
                results[name] = {"device_count": len(devices), "devices": devices}
            except Exception as e:
                results[name] = {"error": str(e)}
        return results

    @mcp.tool
    async def abb_get_task_status(nas: str, device_name: str) -> dict:
        """Get the current/last backup task status for one enrolled device.

        UNVERIFIED — see module docstring. Expected to map to something like
        SYNO.ActiveBackup.Task / get or SYNO.ActiveBackup.Task.Status,
        scoped by device_name.

        Args:
            nas: NAS name (e.g., 'vault'). Required.
            device_name: The device's name as shown in Active Backup for
                         Business (e.g. 'hServer-L1').
        """
        if not client.direct:
            return {"error": "Direct API client not initialized"}

        connections = client.direct.get_connections(nas)
        if not connections:
            return {"error": f"NAS '{nas}' not found or not connected"}

        name = nas.lower()
        conn = connections[name]
        try:
            data = await conn.call(
                "SYNO.ActiveBackup.Task",
                "get",
                version=1,
                device_name=device_name,
            )
            return {
                "nas": name,
                "device_name": device_name,
                "status": data.get("status"),
                "progress": data.get("progress"),
                "last_result": data.get("last_bkp_result") or data.get("result"),
                "last_backup_time": data.get("last_bkp_time"),
                "next_scheduled_time": data.get("next_bkp_time"),
            }
        except Exception as e:
            return {"error": str(e), "nas": name, "device_name": device_name}

    @mcp.tool
    async def abb_list_restore_points(nas: str, device_name: str) -> dict:
        """List available restore points (backup versions) for one device.

        UNVERIFIED — see module docstring. Expected to map to something like
        SYNO.ActiveBackup.Version / list, scoped by device_name.

        Args:
            nas: NAS name (e.g., 'vault'). Required.
            device_name: The device's name as shown in Active Backup for
                         Business (e.g. 'hServer-L1').
        """
        if not client.direct:
            return {"error": "Direct API client not initialized"}

        connections = client.direct.get_connections(nas)
        if not connections:
            return {"error": f"NAS '{nas}' not found or not connected"}

        name = nas.lower()
        conn = connections[name]
        try:
            data = await conn.call(
                "SYNO.ActiveBackup.Version",
                "list",
                version=1,
                device_name=device_name,
            )
            points = [
                {
                    "created_time": v.get("time") or v.get("created_time"),
                    "size_bytes": v.get("size"),
                    "verified": v.get("is_verified") or v.get("verified"),
                }
                for v in data.get("versions", data.get("items", []))
            ]
            return {"nas": name, "device_name": device_name, "restore_point_count": len(points), "restore_points": points}
        except Exception as e:
            return {"error": str(e), "nas": name, "device_name": device_name}


def register_backup_write_tools(mcp: FastMCP, client: SynologyClient) -> None:
    """Mutating Active Backup for Business tools — trigger a backup (confirm-gated)."""

    @mcp.tool
    async def abb_trigger_backup(nas: str, device_name: str, confirm: bool = False) -> dict:
        """Trigger an immediate backup run for one enrolled device.

        UNVERIFIED — see module docstring. Expected to map to something like
        SYNO.ActiveBackup.Task / backup_now, scoped by device_name. Mirrors
        the confirm-gated pattern used by shutdown_nas/reboot_nas in
        tools/power.py — this can be a long-running, resource-intensive
        operation on the NAS.

        Args:
            nas: NAS name (e.g., 'vault'). Required.
            device_name: The device's name as shown in Active Backup for
                         Business (e.g. 'hServer-L1').
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

        if not confirm:
            return {
                "preview": True,
                "action": "trigger_backup",
                "nas": name,
                "device_name": device_name,
                "warning": (
                    f"This will start an immediate Active Backup for Business run for "
                    f"'{device_name}'. It can be long-running and resource-intensive on "
                    "the NAS. Set confirm=True to proceed."
                ),
            }

        try:
            await conn.call(
                "SYNO.ActiveBackup.Task",
                "backup_now",
                version=1,
                device_name=device_name,
            )
            return {
                "success": True,
                "action": "trigger_backup",
                "nas": name,
                "device_name": device_name,
                "message": f"Backup triggered for '{device_name}'.",
            }
        except Exception as e:
            return {"error": str(e), "nas": name, "device_name": device_name}
