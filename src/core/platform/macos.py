import re
import subprocess

from .adapter import AdapterResult, PlatformAdapter

_MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")
# ifconfig flags line example: "flags=8843<UP,BROADCAST,RUNNING,SIMPLEX,MULTICAST>"
_FLAGS_RE = re.compile(r"flags=\w+<([^>]*)>")


def _run(*args: str) -> tuple[int, str, str]:
    result = subprocess.run(list(args), capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr


def _normalize_mac(raw: str) -> str:
    """Ensure MAC is uppercase and colon-separated."""
    return raw.upper().replace("-", ":")


class MacOSAdapter(PlatformAdapter):
    """
    MAC address adapter for macOS using ifconfig.
    Requires elevated privileges for set_mac, bring_interface_down/up.

    Note: get_permanent_mac returns the current MAC as best-effort because
    the hardware MAC on macOS requires IOKit native calls, which are not yet
    implemented. The network state manager (Member 3) must persist the
    pre-change MAC in a state file before calling set_mac.
    """

    def list_interfaces(self) -> AdapterResult:
        try:
            code, out, err = _run("ifconfig", "-l")
            if code != 0:
                return AdapterResult(success=False, error_code="IFCONFIG_FAILED", message=err.strip())

            interfaces = []
            for name in out.strip().split():
                if name == "lo0":
                    continue
                mac_r = self.get_current_mac(name)
                stat_r = self.get_interface_status(name)
                interfaces.append({
                    "name": name,
                    "mac": mac_r.data.get("mac", "") if mac_r.success else "",
                    "is_up": stat_r.data.get("is_up", False) if stat_r.success else False,
                })
            return AdapterResult(success=True, data={"interfaces": interfaces})
        except Exception as exc:
            return AdapterResult(success=False, error_code="UNEXPECTED", message=str(exc))

    def get_current_mac(self, interface: str) -> AdapterResult:
        try:
            code, out, err = _run("ifconfig", interface)
            if code != 0:
                return AdapterResult(success=False, error_code="IFCONFIG_FAILED", message=err.strip())
            match = re.search(r"\bether\s+([0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5})\b", out)
            if not match:
                return AdapterResult(
                    success=False,
                    error_code="MAC_PARSE_FAILED",
                    message=f"No 'ether' field in ifconfig output for '{interface}'",
                )
            return AdapterResult(success=True, data={"mac": _normalize_mac(match.group(1))})
        except Exception as exc:
            return AdapterResult(success=False, error_code="UNEXPECTED", message=str(exc))

    def get_permanent_mac(self, interface: str) -> AdapterResult:
        # macOS does not expose the permanent hardware MAC via a simple shell command.
        # A proper implementation requires IOKit via ctypes or a native helper.
        # Until that is implemented, we return the current MAC with a warning.
        result = self.get_current_mac(interface)
        if result.success:
            result.message = (
                "Permanent MAC via IOKit is not yet implemented; "
                "returning current MAC — may already reflect a spoofed value"
            )
        return result

    def set_mac(self, interface: str, mac: str) -> AdapterResult:
        # Interface should be brought down before calling this on macOS.
        try:
            code, out, err = _run("ifconfig", interface, "lladdr", mac)
            if code != 0:
                return AdapterResult(success=False, error_code="SET_MAC_FAILED", message=err.strip())
            return AdapterResult(success=True, message=f"MAC set to {mac}")
        except Exception as exc:
            return AdapterResult(success=False, error_code="UNEXPECTED", message=str(exc))

    def bring_interface_down(self, interface: str) -> AdapterResult:
        try:
            code, out, err = _run("ifconfig", interface, "down")
            if code != 0:
                return AdapterResult(success=False, error_code="IFACE_DOWN_FAILED", message=err.strip())
            return AdapterResult(success=True, message=f"Interface '{interface}' brought down")
        except Exception as exc:
            return AdapterResult(success=False, error_code="UNEXPECTED", message=str(exc))

    def bring_interface_up(self, interface: str) -> AdapterResult:
        try:
            code, out, err = _run("ifconfig", interface, "up")
            if code != 0:
                return AdapterResult(success=False, error_code="IFACE_UP_FAILED", message=err.strip())
            return AdapterResult(success=True, message=f"Interface '{interface}' brought up")
        except Exception as exc:
            return AdapterResult(success=False, error_code="UNEXPECTED", message=str(exc))

    def get_interface_status(self, interface: str) -> AdapterResult:
        try:
            code, out, err = _run("ifconfig", interface)
            if code != 0:
                return AdapterResult(success=False, error_code="IFCONFIG_FAILED", message=err.strip())
            first_line = out.split("\n")[0] if out else ""
            match = _FLAGS_RE.search(first_line)
            flags = set(match.group(1).split(",")) if match else set()
            return AdapterResult(
                success=True,
                data={
                    "is_up": "UP" in flags,
                    "is_running": "RUNNING" in flags,
                },
            )
        except Exception as exc:
            return AdapterResult(success=False, error_code="UNEXPECTED", message=str(exc))
