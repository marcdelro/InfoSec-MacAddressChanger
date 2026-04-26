"""
Unit tests for the PlatformAdapter contract and MockAdapter behaviour.

These tests run on any OS without elevated privileges or a real NIC.
Run with: pytest tests/unit/test_platform_adapter.py -v
"""

import pytest

from src.core.platform.mock import MockAdapter, _DEFAULT_INTERFACES
from src.core.platform.adapter import AdapterResult


@pytest.fixture
def adapter():
    return MockAdapter()


# ---------------------------------------------------------------------------
# list_interfaces
# ---------------------------------------------------------------------------

class TestListInterfaces:
    def test_returns_default_interfaces(self, adapter):
        result = adapter.list_interfaces()
        assert result.success
        names = {i["name"] for i in result.data["interfaces"]}
        assert names == set(_DEFAULT_INTERFACES.keys())

    def test_each_interface_has_required_keys(self, adapter):
        result = adapter.list_interfaces()
        for iface in result.data["interfaces"]:
            assert "name" in iface
            assert "mac" in iface
            assert "is_up" in iface


# ---------------------------------------------------------------------------
# get_current_mac
# ---------------------------------------------------------------------------

class TestGetCurrentMac:
    def test_returns_mac_for_known_interface(self, adapter):
        result = adapter.get_current_mac("eth0")
        assert result.success
        assert result.data["mac"] == "aa:bb:cc:dd:ee:ff"

    def test_fails_for_unknown_interface(self, adapter):
        result = adapter.get_current_mac("nonexistent0")
        assert not result.success
        assert result.error_code == "IFACE_NOT_FOUND"

    def test_reflects_mac_after_change(self, adapter):
        adapter.bring_interface_down("eth0")
        adapter.set_mac("eth0", "de:ad:be:ef:00:01")
        result = adapter.get_current_mac("eth0")
        assert result.success
        assert result.data["mac"] == "de:ad:be:ef:00:01"


# ---------------------------------------------------------------------------
# get_permanent_mac
# ---------------------------------------------------------------------------

class TestGetPermanentMac:
    def test_returns_permanent_mac(self, adapter):
        result = adapter.get_permanent_mac("wlan0")
        assert result.success
        assert result.data["mac"] == "11:22:33:44:55:66"

    def test_permanent_mac_unchanged_after_spoof(self, adapter):
        adapter.bring_interface_down("wlan0")
        adapter.set_mac("wlan0", "ca:fe:ba:be:00:01")
        perm = adapter.get_permanent_mac("wlan0")
        curr = adapter.get_current_mac("wlan0")
        assert perm.success and curr.success
        assert perm.data["mac"] == "11:22:33:44:55:66"
        assert curr.data["mac"] == "ca:fe:ba:be:00:01"


# ---------------------------------------------------------------------------
# set_mac
# ---------------------------------------------------------------------------

class TestSetMac:
    def test_requires_interface_to_be_down(self, adapter):
        # Interface is up by default — set_mac must refuse.
        result = adapter.set_mac("eth0", "aa:aa:aa:aa:aa:aa")
        assert not result.success
        assert result.error_code == "IFACE_MUST_BE_DOWN"

    def test_succeeds_when_interface_is_down(self, adapter):
        adapter.bring_interface_down("eth0")
        result = adapter.set_mac("eth0", "aa:aa:aa:aa:aa:aa")
        assert result.success

    def test_fails_for_unknown_interface(self, adapter):
        result = adapter.set_mac("ghost0", "aa:aa:aa:aa:aa:aa")
        assert not result.success
        assert result.error_code == "IFACE_NOT_FOUND"


# ---------------------------------------------------------------------------
# bring_interface_down / bring_interface_up
# ---------------------------------------------------------------------------

class TestInterfaceToggle:
    def test_bring_down_sets_is_up_false(self, adapter):
        adapter.bring_interface_down("eth0")
        status = adapter.get_interface_status("eth0")
        assert status.success
        assert not status.data["is_up"]
        assert not status.data["is_running"]

    def test_bring_up_sets_is_up_true(self, adapter):
        adapter.bring_interface_down("eth0")
        adapter.bring_interface_up("eth0")
        status = adapter.get_interface_status("eth0")
        assert status.success
        assert status.data["is_up"]
        assert status.data["is_running"]

    def test_bring_down_unknown_interface_fails(self, adapter):
        result = adapter.bring_interface_down("ghost0")
        assert not result.success
        assert result.error_code == "IFACE_NOT_FOUND"


# ---------------------------------------------------------------------------
# Full MAC-change sequence (the contract Member 3 depends on)
# ---------------------------------------------------------------------------

class TestMacChangeSequence:
    def test_full_sequence_succeeds(self, adapter):
        new_mac = "ca:fe:ba:be:12:34"

        down = adapter.bring_interface_down("wlan0")
        assert down.success

        change = adapter.set_mac("wlan0", new_mac)
        assert change.success

        up = adapter.bring_interface_up("wlan0")
        assert up.success

        status = adapter.get_interface_status("wlan0")
        assert status.data["is_up"] and status.data["is_running"]

        mac = adapter.get_current_mac("wlan0")
        assert mac.data["mac"] == new_mac

    def test_call_log_records_correct_sequence(self, adapter):
        adapter.bring_interface_down("wlan0")
        adapter.set_mac("wlan0", "ca:fe:ba:be:12:34")
        adapter.bring_interface_up("wlan0")

        methods = [entry[0] for entry in adapter.call_log]
        assert methods == ["bring_interface_down", "set_mac", "bring_interface_up"]


# ---------------------------------------------------------------------------
# MockAdapter helpers
# ---------------------------------------------------------------------------

class TestMockHelpers:
    def test_add_interface(self, adapter):
        adapter.add_interface("eth1", "de:ad:de:ad:de:ad")
        result = adapter.get_current_mac("eth1")
        assert result.success
        assert result.data["mac"] == "de:ad:de:ad:de:ad"

    def test_reset_restores_defaults(self, adapter):
        adapter.bring_interface_down("eth0")
        adapter.set_mac("eth0", "ff:ff:ff:ff:ff:ff")
        adapter.reset()
        # call_log is cleared by reset; the get_current_mac call below is the first entry
        assert adapter.call_log == []
        result = adapter.get_current_mac("eth0")
        assert result.data["mac"] == "aa:bb:cc:dd:ee:ff"
