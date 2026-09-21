"""DNS Server package tools (Eddington fork extension — see docs/EDDINGTON_EXTENSIONS.md).

Read tools (dns_list_zones, dns_list_records) are VERIFIED — tested live against
Vault (Synology DS718+, DSM 7.3.2, DNS Server package) on 2026-09-21 via
discover_apis + direct conn.call probing. Real field names, not guesses:

- SYNO.DNSServer.Zone / list (no params) -> {"items": [...], "total": N}, each
  item: domain_name, zone_name, zone_type, zone_enable, is_readonly.
- SYNO.DNSServer.Zone.Record / list (params: domain_name AND zone_name, both
  required, both equal to the zone e.g. "eddington.place") ->
  {"items": [...], "total": N}, each item: rr_owner, rr_type, rr_info, rr_ttl,
  full_record.

Write tools (dns_create_record, dns_delete_record) are STILL UNVERIFIED — the
method names ("create"/"delete") and whether they take the same
domain_name+zone_name pair as list, plus the rr_owner/rr_type/rr_info/rr_ttl
param shape, are an educated guess extrapolated from the verified list schema,
not tested live (a live test would actually mutate the eddington.place zone).
Verify against a disposable test zone/record before trusting these.
"""

from fastmcp import FastMCP

from ..client import SynologyClient


def register_dns_read_tools(mcp: FastMCP, client: SynologyClient) -> None:
    """Read-only DNS Server tools — zone and record listing. VERIFIED 2026-09-21."""

    @mcp.tool
    async def dns_list_zones(nas: str | None = None) -> dict:
        """List DNS Server zones configured on the NAS.

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
                        "zone_name": z.get("zone_name"),
                        "domain_name": z.get("domain_name"),
                        "zone_type": z.get("zone_type"),
                        "enabled": z.get("zone_enable"),
                        "readonly": z.get("is_readonly"),
                    }
                    for z in data.get("items", [])
                ]
                results[name] = {"zone_count": data.get("total", len(zones)), "zones": zones}
            except Exception as e:
                results[name] = {"error": str(e)}
        return results

    @mcp.tool
    async def dns_list_records(nas: str, zone_name: str) -> dict:
        """List resource records within a DNS Server zone.

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
                "SYNO.DNSServer.Zone.Record",
                "list",
                version=1,
                domain_name=zone_name,
                zone_name=zone_name,
            )
            records = [
                {
                    "name": r.get("rr_owner"),
                    "type": r.get("rr_type"),
                    "value": r.get("rr_info"),
                    "ttl": r.get("rr_ttl"),
                }
                for r in data.get("items", [])
            ]
            return {"zone_name": zone_name, "record_count": data.get("total", len(records)), "records": records}
        except Exception as e:
            return {"error": str(e), "nas": name, "zone_name": zone_name}


def register_dns_write_tools(mcp: FastMCP, client: SynologyClient) -> None:
    """Mutating DNS Server tools — record create/delete (confirm-gated). UNVERIFIED."""

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

        STILL UNVERIFIED — see module docstring. The list schema (rr_owner/
        rr_type/rr_info/rr_ttl, domain_name+zone_name params) is confirmed live;
        the create method name and whether it accepts this same param shape is
        not — verify against a disposable test record before trusting this.

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
                    f"'{zone_name}' pointing to '{value}'. Set confirm=True to proceed. "
                    "NOTE: this call is UNVERIFIED against a real DSM instance."
                ),
            }

        try:
            await conn.call(
                "SYNO.DNSServer.Zone.Record",
                "create",
                version=1,
                domain_name=zone_name,
                zone_name=zone_name,
                rr_owner=record_name,
                rr_type=record_type,
                rr_info=value,
                rr_ttl=str(ttl),
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

        STILL UNVERIFIED — see module docstring and dns_create_record's caveat.

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
                    f"'{record_name}' from zone '{zone_name}'. Set confirm=True to proceed. "
                    "NOTE: this call is UNVERIFIED against a real DSM instance."
                ),
            }

        try:
            await conn.call(
                "SYNO.DNSServer.Zone.Record",
                "delete",
                version=1,
                domain_name=zone_name,
                zone_name=zone_name,
                rr_owner=record_name,
                rr_type=record_type,
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
