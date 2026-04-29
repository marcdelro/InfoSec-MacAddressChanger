import ctypes
import ctypes.util
import re
import subprocess

from .adapter import AdapterResult, PlatformAdapter

_MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")
# ifconfig flags line example: "flags=8843<UP,BROADCAST,RUNNING,SIMPLEX,MULTICAST>"
_FLAGS_RE = re.compile(r"flags=\w+<([^>]*)>")

_kCFStringEncodingUTF8 = 0x08000100
# kIOMasterPortDefault / kIOMainPortDefault — the constant value is 0 on all macOS versions.
_kIOMainPortDefault = 0


def _load_frameworks() -> tuple | None:
    """Load IOKit and CoreFoundation via ctypes. Returns (iokit, cf) or None."""
    try:
        iokit_path = ctypes.util.find_library("IOKit")
        cf_path = ctypes.util.find_library("CoreFoundation")
        if not iokit_path or not cf_path:
            return None
        iokit = ctypes.cdll.LoadLibrary(iokit_path)
        cf = ctypes.cdll.LoadLibrary(cf_path)
        return iokit, cf
    except OSError:
        return None


def _configure_iokit(iokit: ctypes.CDLL, cf: ctypes.CDLL) -> None:
    """Annotate IOKit and CoreFoundation function signatures for type safety."""
    iokit.IOServiceMatching.restype = ctypes.c_void_p
    iokit.IOServiceMatching.argtypes = [ctypes.c_char_p]

    iokit.IOServiceGetMatchingServices.restype = ctypes.c_int
    iokit.IOServiceGetMatchingServices.argtypes = [
        ctypes.c_uint,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_uint),
    ]

    iokit.IOIteratorNext.restype = ctypes.c_uint
    iokit.IOIteratorNext.argtypes = [ctypes.c_uint]

    iokit.IORegistryEntryCreateCFProperties.restype = ctypes.c_int
    iokit.IORegistryEntryCreateCFProperties.argtypes = [
        ctypes.c_uint,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_void_p,
        ctypes.c_uint,
    ]

    iokit.IOObjectRelease.restype = ctypes.c_int
    iokit.IOObjectRelease.argtypes = [ctypes.c_uint]

    cf.CFStringCreateWithCString.restype = ctypes.c_void_p
    cf.CFStringCreateWithCString.argtypes = [
        ctypes.c_void_p,
        ctypes.c_char_p,
        ctypes.c_uint32,
    ]

    cf.CFStringGetCString.restype = ctypes.c_bool
    cf.CFStringGetCString.argtypes = [
        ctypes.c_void_p,
        ctypes.c_char_p,
        ctypes.c_long,
        ctypes.c_uint32,
    ]

    cf.CFDictionaryGetValue.restype = ctypes.c_void_p
    cf.CFDictionaryGetValue.argtypes = [ctypes.c_void_p, ctypes.c_void_p]

    cf.CFDataGetLength.restype = ctypes.c_long
    cf.CFDataGetLength.argtypes = [ctypes.c_void_p]

    cf.CFDataGetBytePtr.restype = ctypes.c_void_p
    cf.CFDataGetBytePtr.argtypes = [ctypes.c_void_p]

    cf.CFRelease.restype = None
    cf.CFRelease.argtypes = [ctypes.c_void_p]


def _iokit_get_permanent_mac(interface: str) -> str | None:
    """
    Walk the IOKit registry to find the IONetworkInterface entry whose BSD name
    matches `interface` and return its IOMACAddress (the factory-burned hardware
    address) as an uppercase colon-separated string, or None on any failure.

    IOServiceGetMatchingServices consumes (releases) the matching dict, so we
    must not call CFRelease on it ourselves.
    """
    libs = _load_frameworks()
    if libs is None:
        return None
    iokit, cf = libs
    _configure_iokit(iokit, cf)

    matching = iokit.IOServiceMatching(b"IONetworkInterface")
    if not matching:
        return None

    iterator = ctypes.c_uint(0)
    # KERN_SUCCESS == 0; matching dict ownership is transferred here.
    if iokit.IOServiceGetMatchingServices(_kIOMainPortDefault, matching, ctypes.byref(iterator)) != 0:
        return None

    found_mac: str | None = None
    try:
        while True:
            service = iokit.IOIteratorNext(iterator)
            if not service:
                break
            try:
                props = ctypes.c_void_p(0)
                if iokit.IORegistryEntryCreateCFProperties(service, ctypes.byref(props), None, 0) != 0:
                    continue
                if not props:
                    continue
                try:
                    bsd_key = cf.CFStringCreateWithCString(None, b"BSD Name", _kCFStringEncodingUTF8)
                    if not bsd_key:
                        continue
                    bsd_val = cf.CFDictionaryGetValue(props, bsd_key)
                    cf.CFRelease(bsd_key)
                    if not bsd_val:
                        continue

                    buf = ctypes.create_string_buffer(64)
                    if not cf.CFStringGetCString(bsd_val, buf, 64, _kCFStringEncodingUTF8):
                        continue
                    if buf.value.decode() != interface:
                        continue

                    mac_key = cf.CFStringCreateWithCString(None, b"IOMACAddress", _kCFStringEncodingUTF8)
                    if not mac_key:
                        continue
                    mac_data = cf.CFDictionaryGetValue(props, mac_key)
                    cf.CFRelease(mac_key)
                    if not mac_data:
                        continue

                    length = cf.CFDataGetLength(mac_data)
                    if length != 6:
                        continue
                    ptr = cf.CFDataGetBytePtr(mac_data)
                    raw_bytes = (ctypes.c_uint8 * 6).from_address(ptr)
                    found_mac = ":".join(f"{b:02X}" for b in raw_bytes)
                finally:
                    cf.CFRelease(props)
            finally:
                iokit.IOObjectRelease(service)

            if found_mac:
                break
    finally:
        iokit.IOObjectRelease(iterator)

    return found_mac


def _run(*args: str) -> tuple[int, str, str]:
    result = subprocess.run(list(args), capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr


def _normalize_mac(raw: str) -> str:
    """Ensure MAC is uppercase and colon-separated."""
    return raw.upper().replace("-", ":")


class MacOSAdapter(PlatformAdapter):
    """
    MAC address adapter for macOS using ifconfig and IOKit.
    Requires elevated privileges for set_mac, bring_interface_down/up.
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
        mac = _iokit_get_permanent_mac(interface)
        if mac:
            return AdapterResult(success=True, data={"mac": mac})

        # IOKit unavailable or interface not found — fall back to current MAC.
        result = self.get_current_mac(interface)
        if result.success:
            result.message = (
                "IOKit permanent MAC unavailable; returning current MAC "
                "(may already reflect a spoofed value — persist pre-change MAC in state file)"
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
