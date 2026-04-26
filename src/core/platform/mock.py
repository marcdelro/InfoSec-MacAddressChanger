"""
Mock platform adapter for development and unit testing.

Set the environment variable MAC_ADAPTER=mock to use this adapter:
    MAC_ADAPTER=mock npm run dev
    MAC_ADAPTER=mock pytest tests/unit/

The mock is stateful — it tracks interface state across calls so that tests
can verify the correct bring-down → set_mac → bring-up call sequence.
"""

from copy import deepcopy
from dataclasses import dataclass, field

from .adapter import AdapterResult, PlatformAdapter


@dataclass
class _InterfaceState:
    mac: str
    permanent_mac: str
    is_up: bool = True
    is_running: bool = True


_DEFAULT_INTERFACES: dict[str, _InterfaceState] = {
    "eth0": _InterfaceState(
        mac="aa:bb:cc:dd:ee:ff",
        permanent_mac="aa:bb:cc:dd:ee:ff",
    ),
    "wlan0": _InterfaceState(
        mac="11:22:33:44:55:66",
        permanent_mac="11:22:33:44:55:66",
    ),
}


class MockAdapter(PlatformAdapter):
    """
    In-memory adapter that simulates OS behaviour without touching the system.

    Useful for frontend development, unit tests, and CI runs that lack a
    physical NIC. The call_log records every method call and its arguments
    so tests can assert the correct sequence was followed.
    """

    def __init__(self, interfaces: dict[str, _InterfaceState] | None = None) -> None:
        self._interfaces: dict[str, _InterfaceState] = (
            deepcopy(interfaces) if interfaces is not None else deepcopy(_DEFAULT_INTERFACES)
        )
        self.call_log: list[tuple[str, tuple]] = []

    # ------------------------------------------------------------------
    # PlatformAdapter implementation
    # ------------------------------------------------------------------

    def list_interfaces(self) -> AdapterResult:
        self._log("list_interfaces")
        interfaces = [
            {"name": name, "mac": state.mac, "is_up": state.is_up}
            for name, state in self._interfaces.items()
        ]
        return AdapterResult(success=True, data={"interfaces": interfaces})

    def get_current_mac(self, interface: str) -> AdapterResult:
        self._log("get_current_mac", interface)
        state = self._interfaces.get(interface)
        if state is None:
            return self._not_found(interface)
        return AdapterResult(success=True, data={"mac": state.mac})

    def get_permanent_mac(self, interface: str) -> AdapterResult:
        self._log("get_permanent_mac", interface)
        state = self._interfaces.get(interface)
        if state is None:
            return self._not_found(interface)
        return AdapterResult(success=True, data={"mac": state.permanent_mac})

    def set_mac(self, interface: str, mac: str) -> AdapterResult:
        self._log("set_mac", interface, mac)
        state = self._interfaces.get(interface)
        if state is None:
            return self._not_found(interface)
        if state.is_up:
            return AdapterResult(
                success=False,
                error_code="IFACE_MUST_BE_DOWN",
                message=f"Interface '{interface}' must be brought down before changing MAC",
            )
        state.mac = mac
        return AdapterResult(success=True, message=f"MAC set to {mac}")

    def bring_interface_down(self, interface: str) -> AdapterResult:
        self._log("bring_interface_down", interface)
        state = self._interfaces.get(interface)
        if state is None:
            return self._not_found(interface)
        state.is_up = False
        state.is_running = False
        return AdapterResult(success=True, message=f"Interface '{interface}' brought down")

    def bring_interface_up(self, interface: str) -> AdapterResult:
        self._log("bring_interface_up", interface)
        state = self._interfaces.get(interface)
        if state is None:
            return self._not_found(interface)
        state.is_up = True
        state.is_running = True
        return AdapterResult(success=True, message=f"Interface '{interface}' brought up")

    def get_interface_status(self, interface: str) -> AdapterResult:
        self._log("get_interface_status", interface)
        state = self._interfaces.get(interface)
        if state is None:
            return self._not_found(interface)
        return AdapterResult(
            success=True,
            data={"is_up": state.is_up, "is_running": state.is_running},
        )

    # ------------------------------------------------------------------
    # Test helpers
    # ------------------------------------------------------------------

    def add_interface(self, name: str, mac: str, permanent_mac: str | None = None) -> None:
        """Inject a synthetic interface for testing edge cases."""
        self._interfaces[name] = _InterfaceState(
            mac=mac,
            permanent_mac=permanent_mac or mac,
        )

    def reset(self) -> None:
        """Restore default interface state and clear the call log."""
        self._interfaces = deepcopy(_DEFAULT_INTERFACES)
        self.call_log.clear()

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _log(self, method: str, *args) -> None:
        self.call_log.append((method, args))

    @staticmethod
    def _not_found(interface: str) -> AdapterResult:
        return AdapterResult(
            success=False,
            error_code="IFACE_NOT_FOUND",
            message=f"Interface '{interface}' does not exist in mock",
        )
