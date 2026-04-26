"""
Windows MAC address adapter.

MAC changes are written to the NIC's registry subkey under:
  HKLM\\SYSTEM\\CurrentControlSet\\Control\\Class\\{4D36E972-E325-11CE-BFC1-08002BE10318}

This requires elevation. In production the adapter is invoked from the UAC
helper service (Member 2) — never directly from the unprivileged GUI process.

Interface bring-down/up use `netsh interface set interface` with argument
lists (no shell=True, no string interpolation).
"""

import csv
import io
import json
import re
import subprocess
import sys

if sys.platform != "win32":
    raise ImportError("WindowsAdapter is only available on Windows")

import winreg

from .adapter import AdapterResult, PlatformAdapter

_MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")

# Registry paths
_ADAPTER_CLASS_KEY = (
    r"SYSTEM\CurrentControlSet\Control\Class"
    r"\{4D36E972-E325-11CE-BFC1-08002BE10318}"
)
_NETWORK_KEY = (
    r"SYSTEM\CurrentControlSet\Control\Network"
    r"\{4D36E972-E325-11CE-BFC1-08002BE10318}"
)


def _run(*args: str) -> tuple[int, str, str]:
    result = subprocess.run(list(args), capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr


def _normalize_mac(raw: str) -> str:
    """Normalise any XX-XX or XX:XX format to uppercase colon-separated."""
    return raw.upper().replace("-", ":")


def _mac_to_registry_value(mac: str) -> str:
    """Strip separators for the registry NetworkAddress value (AABBCCDDEEFF)."""
    return mac.upper().replace(":", "").replace("-", "")


def _parse_getmac_csv(output: str) -> list[dict]:
    """
    Parse `getmac /fo csv /v /nh` output into a list of dicts with keys:
      connection_name, adapter, mac, transport
    Rows with 'N/A' MAC (e.g. disconnected VPN adapters) are skipped.
    """
    reader = csv.reader(io.StringIO(output.strip()))
    results = []
    for row in reader:
        if len(row) < 4:
            continue
        connection_name, adapter, mac, transport = (r.strip() for r in row[:4])
        if mac == "N/A" or not mac:
            continue
        results.append({
            "connection_name": connection_name,
            "adapter": adapter,
            "mac": _normalize_mac(mac),
            "transport": transport,
        })
    return results


def _get_adapter_guid(interface_name: str) -> str | None:
    """
    Resolve a human-readable connection name (e.g. "Wi-Fi") to its GUID by
    walking HKLM\\...\\Control\\Network\\{4D36E972...}\\<GUID>\\Connection\\Name.
    """
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _NETWORK_KEY) as net_key:
            idx = 0
            while True:
                try:
                    guid = winreg.EnumKey(net_key, idx)
                    conn_path = f"{_NETWORK_KEY}\\{guid}\\Connection"
                    try:
                        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, conn_path) as conn_key:
                            name, _ = winreg.QueryValueEx(conn_key, "Name")
                            if name.lower() == interface_name.lower():
                                return guid
                    except OSError:
                        pass
                    idx += 1
                except OSError:
                    break
    except OSError:
        pass
    return None


def _get_class_subkey(guid: str) -> str | None:
    """
    Find the numeric subkey (e.g. "0001") under the adapter Class key whose
    NetCfgInstanceId matches the given adapter GUID.
    """
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _ADAPTER_CLASS_KEY) as class_key:
            idx = 0
            while True:
                try:
                    subkey_name = winreg.EnumKey(class_key, idx)
                    subkey_path = f"{_ADAPTER_CLASS_KEY}\\{subkey_name}"
                    try:
                        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, subkey_path) as subkey:
                            net_cfg_id, _ = winreg.QueryValueEx(subkey, "NetCfgInstanceId")
                            if net_cfg_id.lower() == guid.lower():
                                return subkey_name
                    except OSError:
                        pass
                    idx += 1
                except OSError:
                    break
    except OSError:
        pass
    return None


class WindowsAdapter(PlatformAdapter):
    """
    MAC address adapter for Windows 10/11.

    Reads use getmac and PowerShell Get-NetAdapter.
    Writes use winreg (requires elevation via the UAC helper service).
    Interface control uses netsh with argument lists.
    """

    def list_interfaces(self) -> AdapterResult:
        try:
            code, out, err = _run("getmac", "/fo", "csv", "/v", "/nh")
            if code != 0:
                return AdapterResult(success=False, error_code="GETMAC_FAILED", message=err.strip())
            rows = _parse_getmac_csv(out)
            interfaces = [
                {"name": r["connection_name"], "mac": r["mac"], "is_up": True}
                for r in rows
            ]
            # Enrich is_up from Get-NetAdapter output.
            status_map = self._get_all_adapter_statuses()
            for iface in interfaces:
                if iface["name"] in status_map:
                    iface["is_up"] = status_map[iface["name"]].get("is_up", True)
            return AdapterResult(success=True, data={"interfaces": interfaces})
        except Exception as exc:
            return AdapterResult(success=False, error_code="UNEXPECTED", message=str(exc))

    def get_current_mac(self, interface: str) -> AdapterResult:
        try:
            code, out, err = _run("getmac", "/fo", "csv", "/v", "/nh")
            if code != 0:
                return AdapterResult(success=False, error_code="GETMAC_FAILED", message=err.strip())
            for row in _parse_getmac_csv(out):
                if row["connection_name"].lower() == interface.lower():
                    return AdapterResult(success=True, data={"mac": row["mac"]})
            return AdapterResult(
                success=False,
                error_code="IFACE_NOT_FOUND",
                message=f"Interface '{interface}' not found",
            )
        except Exception as exc:
            return AdapterResult(success=False, error_code="UNEXPECTED", message=str(exc))

    def get_permanent_mac(self, interface: str) -> AdapterResult:
        # PowerShell Get-NetAdapter exposes PermanentAddress via NDIS miniport query.
        # We list all adapters and filter in Python to avoid embedding the interface
        # name inside the PowerShell command string.
        try:
            adapters = self._get_all_adapter_statuses()
            if interface in adapters and "permanent_mac" in adapters[interface]:
                mac = adapters[interface]["permanent_mac"]
                if mac:
                    return AdapterResult(success=True, data={"mac": _normalize_mac(mac)})
        except Exception:
            pass

        # Fallback to current MAC.
        result = self.get_current_mac(interface)
        if result.success:
            result.message = "PermanentAddress unavailable; returning current MAC"
        return result

    def set_mac(self, interface: str, mac: str) -> AdapterResult:
        """
        Write the MAC to the adapter's registry NetworkAddress value.
        Must be called from an elevated context (UAC helper service).
        The caller (NetworkStateManager) is responsible for bring-down/up.
        """
        try:
            guid = _get_adapter_guid(interface)
            if guid is None:
                return AdapterResult(
                    success=False,
                    error_code="GUID_NOT_FOUND",
                    message=f"Could not resolve GUID for interface '{interface}'",
                )
            subkey = _get_class_subkey(guid)
            if subkey is None:
                return AdapterResult(
                    success=False,
                    error_code="SUBKEY_NOT_FOUND",
                    message=f"Could not find Class subkey for GUID {guid}",
                )
            reg_path = f"{_ADAPTER_CLASS_KEY}\\{subkey}"
            reg_value = _mac_to_registry_value(mac)
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                reg_path,
                access=winreg.KEY_SET_VALUE,
            ) as key:
                winreg.SetValueEx(key, "NetworkAddress", 0, winreg.REG_SZ, reg_value)
            return AdapterResult(success=True, message=f"Registry NetworkAddress set to {reg_value}")
        except PermissionError:
            return AdapterResult(
                success=False,
                error_code="ELEVATION_REQUIRED",
                message="Writing to HKLM requires Administrator privileges",
            )
        except Exception as exc:
            return AdapterResult(success=False, error_code="UNEXPECTED", message=str(exc))

    def bring_interface_down(self, interface: str) -> AdapterResult:
        try:
            code, out, err = _run(
                "netsh", "interface", "set", "interface", interface, "admin=disable"
            )
            if code != 0:
                return AdapterResult(success=False, error_code="IFACE_DOWN_FAILED", message=err.strip())
            return AdapterResult(success=True, message=f"Interface '{interface}' disabled")
        except Exception as exc:
            return AdapterResult(success=False, error_code="UNEXPECTED", message=str(exc))

    def bring_interface_up(self, interface: str) -> AdapterResult:
        try:
            code, out, err = _run(
                "netsh", "interface", "set", "interface", interface, "admin=enable"
            )
            if code != 0:
                return AdapterResult(success=False, error_code="IFACE_UP_FAILED", message=err.strip())
            return AdapterResult(success=True, message=f"Interface '{interface}' enabled")
        except Exception as exc:
            return AdapterResult(success=False, error_code="UNEXPECTED", message=str(exc))

    def get_interface_status(self, interface: str) -> AdapterResult:
        try:
            statuses = self._get_all_adapter_statuses()
            if interface not in statuses:
                return AdapterResult(
                    success=False,
                    error_code="IFACE_NOT_FOUND",
                    message=f"Interface '{interface}' not found",
                )
            s = statuses[interface]
            return AdapterResult(
                success=True,
                data={"is_up": s.get("is_up", False), "is_running": s.get("is_running", False)},
            )
        except Exception as exc:
            return AdapterResult(success=False, error_code="UNEXPECTED", message=str(exc))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_all_adapter_statuses(self) -> dict[str, dict]:
        """
        Run `Get-NetAdapter | ConvertTo-Json` once and return a dict keyed by
        interface name. Filtering is done in Python — no interface name is
        embedded in the PowerShell command string.
        """
        code, out, err = _run(
            "powershell",
            "-NonInteractive",
            "-NoProfile",
            "-Command",
            "Get-NetAdapter | ConvertTo-Json -Depth 2",
        )
        if code != 0:
            return {}
        try:
            raw = json.loads(out)
            # ConvertTo-Json returns a single object (not array) for one adapter.
            if isinstance(raw, dict):
                raw = [raw]
            result: dict[str, dict] = {}
            for adapter in raw:
                name = adapter.get("Name", "")
                status = adapter.get("Status", "")
                result[name] = {
                    "is_up": status in ("Up", "Disconnected"),
                    "is_running": status == "Up",
                    "permanent_mac": adapter.get("PermanentAddress", ""),
                }
            return result
        except (json.JSONDecodeError, KeyError):
            return {}
