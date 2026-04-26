import os
import sys

from .adapter import AdapterResult, PlatformAdapter


def get_adapter() -> PlatformAdapter:
    """
    Return the correct PlatformAdapter for the current OS.
    Set MAC_ADAPTER=mock to use the mock adapter (no real OS calls).
    """
    adapter_env = os.environ.get("MAC_ADAPTER", "").lower()
    if adapter_env == "mock":
        from .mock import MockAdapter
        return MockAdapter()

    if sys.platform.startswith("linux"):
        from .linux import LinuxAdapter
        return LinuxAdapter()
    elif sys.platform == "darwin":
        from .macos import MacOSAdapter
        return MacOSAdapter()
    elif sys.platform == "win32":
        from .windows import WindowsAdapter
        return WindowsAdapter()
    else:
        raise RuntimeError(f"Unsupported platform: {sys.platform}")


__all__ = ["PlatformAdapter", "AdapterResult", "get_adapter"]
