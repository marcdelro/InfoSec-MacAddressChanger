import json
import re
import subprocess
from pathlib import Path

from .adapter import AdapterResult, PlatformAdapter

_MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")
_SYS_NET = Path("/sys/class/net")


def _run(*args: str) -> tuple[int, str, str]:
    result = subprocess.run(list(args), capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr


class LinuxAdapter(PlatformAdapter):
    """
    MAC address adapter for Linux using iproute2 (ip) with ifconfig fallback.
    Requires elevated privileges for set_mac, bring_interface_down/up.
    """

    def list_interfaces(self) -> AdapterResult:
        try:
            code, out, err = _run("ip", "-j", "link", "show")
            if code != 0:
                return AdapterResult(success=False, error_code="IP_CMD_FAILED", message=err.strip())
            links = json.loads(out)
            interfaces = [
                {
                    "name": link["ifname"],
                    "mac": link.get("address", ""),
                    "is_up": "UP" in link.get("flags", []),
                }
                for link in links
                if link.get("link_type") != "loopback"
            ]
            return AdapterResult(success=True, data={"interfaces": interfaces})
        except json.JSONDecodeError as exc:
            return AdapterResult(success=False, error_code="PARSE_FAILED", message=str(exc))
        except Exception as exc:
            return AdapterResult(success=False, error_code="UNEXPECTED", message=str(exc))

    def get_current_mac(self, interface: str) -> AdapterResult:
        # Read directly from sysfs — faster than spawning a process.
        try:
            mac = (_SYS_NET / interface / "address").read_text().strip()
            if not _MAC_RE.match(mac):
                return AdapterResult(
                    success=False,
                    error_code="INVALID_MAC",
                    message=f"Unexpected sysfs value: {mac}",
                )
            return AdapterResult(success=True, data={"mac": mac})
        except FileNotFoundError:
            return AdapterResult(
                success=False,
                error_code="IFACE_NOT_FOUND",
                message=f"Interface '{interface}' not found in /sys/class/net",
            )
        except Exception as exc:
            return AdapterResult(success=False, error_code="UNEXPECTED", message=str(exc))

    def get_permanent_mac(self, interface: str) -> AdapterResult:
        # Try kernel-exposed permaddr first (iproute2 >= 4.x / Linux >= 4.x).
        try:
            code, out, err = _run("ip", "-j", "link", "show", interface)
            if code == 0:
                data = json.loads(out)
                if data and "permaddr" in data[0]:
                    return AdapterResult(success=True, data={"mac": data[0]["permaddr"]})
        except Exception:
            pass

        # Fallback: ethtool -P reports the hardware address from the driver.
        try:
            code, out, err = _run("ethtool", "-P", interface)
            if code == 0:
                match = re.search(r"Permanent address:\s+([0-9A-Fa-f:]{17})", out)
                if match:
                    return AdapterResult(success=True, data={"mac": match.group(1)})
        except FileNotFoundError:
            pass  # ethtool not installed on this system

        # Last resort: return current MAC with a warning.
        result = self.get_current_mac(interface)
        if result.success:
            result.message = "Permanent MAC unavailable; returning current MAC (may already be spoofed)"
        return result

    def set_mac(self, interface: str, mac: str) -> AdapterResult:
        # Interface must be brought down by the caller before this is invoked.
        try:
            code, out, err = _run("ip", "link", "set", interface, "address", mac)
            if code == 0:
                return AdapterResult(success=True, message=f"MAC set to {mac} (via ip)")
        except FileNotFoundError:
            pass  # iproute2 not available — fall through to ifconfig

        # Fallback for older distros without iproute2.
        try:
            code, out, err = _run("ifconfig", interface, "hw", "ether", mac)
            if code != 0:
                return AdapterResult(success=False, error_code="SET_MAC_FAILED", message=err.strip())
            return AdapterResult(success=True, message=f"MAC set to {mac} (via ifconfig)")
        except FileNotFoundError:
            return AdapterResult(
                success=False,
                error_code="NO_TOOL_AVAILABLE",
                message="Neither 'ip' (iproute2) nor 'ifconfig' (net-tools) is available",
            )
        except Exception as exc:
            return AdapterResult(success=False, error_code="UNEXPECTED", message=str(exc))

    def bring_interface_down(self, interface: str) -> AdapterResult:
        try:
            code, out, err = _run("ip", "link", "set", interface, "down")
            if code != 0:
                return AdapterResult(success=False, error_code="IFACE_DOWN_FAILED", message=err.strip())
            return AdapterResult(success=True, message=f"Interface '{interface}' brought down")
        except Exception as exc:
            return AdapterResult(success=False, error_code="UNEXPECTED", message=str(exc))

    def bring_interface_up(self, interface: str) -> AdapterResult:
        try:
            code, out, err = _run("ip", "link", "set", interface, "up")
            if code != 0:
                return AdapterResult(success=False, error_code="IFACE_UP_FAILED", message=err.strip())
            return AdapterResult(success=True, message=f"Interface '{interface}' brought up")
        except Exception as exc:
            return AdapterResult(success=False, error_code="UNEXPECTED", message=str(exc))

    def get_interface_status(self, interface: str) -> AdapterResult:
        try:
            code, out, err = _run("ip", "-j", "link", "show", interface)
            if code != 0:
                return AdapterResult(success=False, error_code="IP_CMD_FAILED", message=err.strip())
            data = json.loads(out)
            if not data:
                return AdapterResult(success=False, error_code="IFACE_NOT_FOUND")
            flags = data[0].get("flags", [])
            return AdapterResult(
                success=True,
                data={
                    "is_up": "UP" in flags,
                    # LOWER_UP means carrier detected — interface is physically connected.
                    "is_running": "LOWER_UP" in flags,
                },
            )
        except json.JSONDecodeError as exc:
            return AdapterResult(success=False, error_code="PARSE_FAILED", message=str(exc))
        except Exception as exc:
            return AdapterResult(success=False, error_code="UNEXPECTED", message=str(exc))
