"""DNS Server package tools (Eddington fork extension — see docs/EDDINGTON_EXTENSIONS.md).

UNVERIFIED ENDPOINT NAMES. The SYNO.DNSServer.* calls below are a best-effort
guess based on Synology's public API naming convention, not confirmed against
a real DSM instance or Synology's official "DNS Server API Guide" PDF. Before
relying on these:

1. Deploy this fork against a NAS with the DNS Server package installed.
2. Run the existing `discover_apis` tool (tools/diagnostic.py) and grep its
   output for "DNSServer" to get the real API names, versions, and CGI paths.
3. Correct every `conn.call(...)` below to match, then remove this notice.

Modeled on the request/response/error-handling shape already used throughout
tools/diagnostic.py (one try/except per NAS connection, soft {"error": ...}
on failure rather than raising).
"""

from fastmcp import FastMCP

from ..client import SynologyClient


def register_dns_read_tools(mcp: FastMCP, client: SynologyClient) -> None:
    """Read-only DNS Server tools — zone and record listing."""

    @mcp.tool
    async def dns_list_zones(nas: str | None = None) -> dict:
        """List DNS Server zones configured on the NAS.

        UNVERIFIED — see module docstring. Expected to map to something like
        SYNO.DNSServer.Zone / list.

        Args:
            nas: NAS name (e.g., 'vault'). If omitted, queries all.
        """
        if not client.direct:
            return {"error": "Direct API client not initialized"}

        results = {}
        for name, conn in client.direct.get_connections(nas).items():
            try:
                data = await conn.call(
                    "SYNO.DNSServer.Zone",
                    "list",
                    version=1,
                )
                zones = [
                    {
                        "name": z.get("zone_name") or z.get("name"),
                        "type": z.get("zone_type") or z.get("type"),
                        "status": z.get("status"),
                    }
                    for z in data.get("zones", data.get("items", []))
                ]
                results[name] = {"zone_count": len(zones), "zones": zones}
            except Exception as e:
                results[name] = {"error": str(e)}
        return results

    @mcp.tool
    async def dns_list_records(nas: str, zone_name: str) -> dict:
        """List resource records within a DNS Server zone.

        UNVERIFIED — see module docstring. Expected to map to something like
        SYNO.DNSServer.Zone.Master.Record / list, scoped by zone_name.

        Args:
            nas: NAS name (e.g., 'vault'). Required — records are per-zone,
                 per-NAS.
            zone_name: The zone to list records from (e.g. 'eddington.place').
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
                "SYNO.DNSServer.Zone.Master.Record",
                "list",
                version=1,
                zone_name=zone_name,
            )
            records = [
                {
                    "name": r.get("owner") or r.get("name"),
                    "type": r.get("type"),
                    "value": r.get("data") or r.get("value"),
                    "ttl": r.get("ttl"),
                }
                for r in data.get("records", data.get("items", []))
            ]
            return {"zone_name": zone_name, "record_count": len(records), "records": records}
        except Exception as e:
            return {"error": str(e), "nas": name, "zone_name": zone_name}


def register_dns_write_tools(mcp: FastMCP, client: SynologyClient) -> None:
    """Mutating DNS Server tools — record create/delete (confirm-gated)."""

    @mcp.tool
    async def dns_create_record(
        nas: str,
        zone_name: str,
        record_name: str,
        record_type: str,
        value: str,
        ttl: int = 86400,
        confirm: bool = False,
    ) -> dict:
        """Create a DNS resource record in a DNS Server zone.

        UNVERIFIED — see module docstring. Expected to map to something like
        SYNO.DNSServer.Zone.Master.Record / create.

        Args:
            nas: NAS name (e.g., 'vault'). Required.
            zone_name: The zone to add the record to (e.g. 'eddington.place').
            record_name: The record's owner name, relative to the zone
                         (e.g. 'hserver-l1' for hserver-l1.eddington.place).
            record_type: Record type, e.g. 'A' or 'CNAME'.
            value: The record's target — an IP for 'A', a hostname for
                   'CNAME'.
            ttl: Time-to-live in seconds. Defaults to 86400, matching the
                 convention already used in this project's LAN DNS runbook.
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
                "action": "create_record",
                "nas": name,
                "zone_name": zone_name,
                "record": {"name": record_name, "type": record_type, "value": value, "ttl": ttl},
                "warning": (
                    f"This will create a {record_type} record '{record_name}' in zone "
                    f"'{zone_name}' pointing to '{value}'. Set confirm=True to proceed."
                ),
            }

        try:
            await conn.call(
                "SYNO.DNSServer.Zone.Master.Record",
                "create",
                version=1,
                zone_name=zone_name,
                name=record_name,
                type=record_type,
                data=value,
                ttl=ttl,
            )
            return {
                "success": True,
                "action": "create_record",
                "nas": name,
                "zone_name": zone_name,
                "record": {"name": record_name, "type": record_type, "value": value, "ttl": ttl},
            }
        except Exception as e:
            return {"error": str(e), "nas": name, "zone_name": zone_name}

    @mcp.tool
    async def dns_delete_record(
        nas: str,
        zone_name: str,
        record_name: str,
        record_type: str,
        confirm: bool = False,
    ) -> dict:
        """Delete a DNS resource record from a DNS Server zone.

        UNVERIFIED — see module docstring. Expected to map to something like
        SYNO.DNSServer.Zone.Master.Record / delete.

        Args:
            nas: NAS name (e.g., 'vault'). Required.
            zone_name: The zone to delete the record from.
            record_name: The record's owner name, relative to the zone.
            record_type: Record type, e.g. 'A' or 'CNAME'.
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
                "action": "delete_record",
                "nas": name,
                "zone_name": zone_name,
                "record": {"name": record_name, "type": record_type},
                "warning": (
                    f"This will permanently delete the {record_type} record "
                    f"'{record_name}' from zone '{zone_name}'. Set confirm=True to proceed."
                ),
            }

        try:
            await conn.call(
                "SYNO.DNSServer.Zone.Master.Record",
                "delete",
                version=1,
                zone_name=zone_name,
                name=record_name,
                type=record_type,
            )
            return {
                "success": True,
                "action": "delete_record",
                "nas": name,
                "zone_name": zone_name,
                "record": {"name": record_name, "type": record_type},
            }
        except Exception as e:
            return {"error": str(e), "nas": name, "zone_name": zone_name}
