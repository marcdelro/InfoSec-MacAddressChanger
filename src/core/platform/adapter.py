from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class AdapterResult:
    success: bool
    error_code: str | None = None
    message: str = ""
    data: dict = field(default_factory=dict)


class PlatformAdapter(ABC):
    """
    OS-level MAC address operations abstraction.

    All upper layers (network manager, IPC handlers) must interact with the OS
    exclusively through this interface — never call subprocess or OS APIs directly.

    Concrete implementations: LinuxAdapter, MacOSAdapter, WindowsAdapter, MockAdapter.
    Use get_adapter() from this package to obtain the correct instance.
    """

    @abstractmethod
    def list_interfaces(self) -> AdapterResult:
        """
        Return all non-loopback network interfaces on the machine.
        data: {"interfaces": [{"name": str, "mac": str, "is_up": bool}, ...]}
        """

    @abstractmethod
    def get_current_mac(self, interface: str) -> AdapterResult:
        """
        Return the MAC address currently active on the interface (may be spoofed).
        data: {"mac": str}  — colon-separated EUI-48, e.g. "AA:BB:CC:DD:EE:FF"
        """

    @abstractmethod
    def get_permanent_mac(self, interface: str) -> AdapterResult:
        """
        Return the factory-burned-in hardware MAC address.
        data: {"mac": str}

        Note: On some platforms/drivers this cannot be distinguished from the
        current MAC once a spoof is active. Callers should treat this as
        best-effort and persist the pre-change MAC in a state file (Member 3).
        """

    @abstractmethod
    def set_mac(self, interface: str, mac: str) -> AdapterResult:
        """
        Write a new MAC address to the interface.

        Precondition (Linux/macOS): the interface must already be down.
        On Windows the registry value is written; the caller is responsible
        for bring-down/bring-up to make the driver pick up the new value.

        mac: colon-separated EUI-48, e.g. "AA:BB:CC:DD:EE:FF"
        This method trusts that mac has already been validated by the security
        layer (Member 2) before reaching here.
        """

    @abstractmethod
    def bring_interface_down(self, interface: str) -> AdapterResult:
        """Administratively disable the interface."""

    @abstractmethod
    def bring_interface_up(self, interface: str) -> AdapterResult:
        """Administratively enable the interface."""

    @abstractmethod
    def get_interface_status(self, interface: str) -> AdapterResult:
        """
        Return the current operational state of the interface.
        data: {"is_up": bool, "is_running": bool}

        is_up      — interface is administratively enabled
        is_running — link is active and carrier is detected (LOWER_UP / RUNNING)
        """
