from typing import Any
import pytest

from chia.wallet.util.address_type import (
    AddressType,
    CurrentNetworkAddressPrefix,
    is_valid_address,
    ensure_valid_address,
)


@pytest.fixture(scope="function")
def override_selected_network_address_prefix(monkeypatch: Any, prefix: str):
    with monkeypatch.context() as m:
        m.setattr("chia.wallet.util.address_type.CurrentNetworkAddressPrefix.current", prefix)
        assert CurrentNetworkAddressPrefix.current == prefix
        yield


@pytest.mark.parametrize("prefix", ["xch"])
def test_is_valid_address_mainnet(override_selected_network_address_prefix):
    valid = is_valid_address("xch1mnr0ygu7lvmk3nfgzmncfk39fwu0dv933yrcv97nd6pmrt7fzmhs8taffd")
    assert valid is True


@pytest.mark.parametrize("prefix", ["txch"])
def test_is_valid_address_testnet(override_selected_network_address_prefix):
    valid = is_valid_address("txch1mnr0ygu7lvmk3nfgzmncfk39fwu0dv933yrcv97nd6pmrt7fzmhs2v6lg7")
    assert valid is True


@pytest.mark.parametrize("prefix", ["xch"])
def test_is_valid_address_mainnet_explicit(override_selected_network_address_prefix):
    valid = is_valid_address(
        "xch1mnr0ygu7lvmk3nfgzmncfk39fwu0dv933yrcv97nd6pmrt7fzmhs8taffd", allowed_types={AddressType.XCH}
    )
    assert valid is True


@pytest.mark.parametrize("prefix", ["txch"])
def test_is_valid_address_testnet_explicit(override_selected_network_address_prefix):
    valid = is_valid_address(
        "txch1mnr0ygu7lvmk3nfgzmncfk39fwu0dv933yrcv97nd6pmrt7fzmhs2v6lg7", allowed_types={AddressType.TXCH}
    )
    assert valid is True


@pytest.mark.parametrize("prefix", ["xch"])
def test_is_valid_address_mainnet_explicit_txch_address(override_selected_network_address_prefix):
    valid = is_valid_address(
        "txch1mnr0ygu7lvmk3nfgzmncfk39fwu0dv933yrcv97nd6pmrt7fzmhs2v6lg7", allowed_types={AddressType.TXCH}
    )
    assert valid is True


@pytest.mark.parametrize("prefix", ["xch"])
def test_is_valid_address_mainnet_bad_address(override_selected_network_address_prefix):
    valid = is_valid_address("xch1mnr0ygu7lvmk3nfgzmncfk39fwu0dv933yrcv97nd6pmrt7fzmhs8xxxxx")
    assert valid is False


def test_is_valid_address_nft():
    valid = is_valid_address(
        "nft1mx2nkvml2eekjtqwdmxvmf3js8g083hpszzhkhtwvhcss8efqzhqtza773", allowed_types={AddressType.NFT}
    )
    assert valid is True


def test_is_valid_address_nft_bad_address():
    valid = is_valid_address(
        "nft1mx2nkvml2eekjtqwdmxvmf3js8g083hpszzhkhtwvhcss8efqzhqtxxxxx", allowed_types={AddressType.NFT}
    )
    assert valid is False


def test_is_valid_address_did():
    valid = is_valid_address(
        "did:chia:14jxdtqcyp3gk8ka0678eq8mmtnktgpmp2vuqq3vtsl2e5qr7fyrsr9gsr7", allowed_types={AddressType.DID}
    )
    assert valid is True


def test_is_valid_address_did_bad_address():
    valid = is_valid_address(
        "did:chia:14jxdtqcyp3gk8ka0678eq8mmtnktgpmp2vuqq3vtsl2e5qr7fyrsrxxxxx", allowed_types={AddressType.DID}
    )
    assert valid is False


@pytest.mark.parametrize("prefix", ["xch"])
def test_ensure_valid_address_mainnet(override_selected_network_address_prefix):
    address = ensure_valid_address("xch1mnr0ygu7lvmk3nfgzmncfk39fwu0dv933yrcv97nd6pmrt7fzmhs8taffd")
    assert address == "xch1mnr0ygu7lvmk3nfgzmncfk39fwu0dv933yrcv97nd6pmrt7fzmhs8taffd"


@pytest.mark.parametrize("prefix", ["txch"])
def test_ensure_valid_address_testnet(override_selected_network_address_prefix):
    address = ensure_valid_address("txch1mnr0ygu7lvmk3nfgzmncfk39fwu0dv933yrcv97nd6pmrt7fzmhs2v6lg7")
    assert address == "txch1mnr0ygu7lvmk3nfgzmncfk39fwu0dv933yrcv97nd6pmrt7fzmhs2v6lg7"


@pytest.mark.parametrize("prefix", ["xch"])
def test_ensure_valid_address_mainnet_explicit(override_selected_network_address_prefix):
    address = ensure_valid_address(
        "xch1mnr0ygu7lvmk3nfgzmncfk39fwu0dv933yrcv97nd6pmrt7fzmhs8taffd", allowed_types={AddressType.XCH}
    )
    assert address == "xch1mnr0ygu7lvmk3nfgzmncfk39fwu0dv933yrcv97nd6pmrt7fzmhs8taffd"


@pytest.mark.parametrize("prefix", ["txch"])
def test_ensure_valid_address_testnet_explicit(override_selected_network_address_prefix):
    address = ensure_valid_address(
        "txch1mnr0ygu7lvmk3nfgzmncfk39fwu0dv933yrcv97nd6pmrt7fzmhs2v6lg7", allowed_types={AddressType.TXCH}
    )
    assert address == "txch1mnr0ygu7lvmk3nfgzmncfk39fwu0dv933yrcv97nd6pmrt7fzmhs2v6lg7"


@pytest.mark.parametrize("prefix", ["xch"])
def test_ensure_valid_address_mainnet_explicit_txch_address(override_selected_network_address_prefix):
    address = ensure_valid_address(
        "txch1mnr0ygu7lvmk3nfgzmncfk39fwu0dv933yrcv97nd6pmrt7fzmhs2v6lg7", allowed_types={AddressType.TXCH}
    )
    assert address == "txch1mnr0ygu7lvmk3nfgzmncfk39fwu0dv933yrcv97nd6pmrt7fzmhs2v6lg7"


@pytest.mark.parametrize("prefix", ["xch"])
def test_ensure_valid_address_mainnet_bad_address(override_selected_network_address_prefix):
    with pytest.raises(ValueError):
        ensure_valid_address("xch1mnr0ygu7lvmk3nfgzmncfk39fwu0dv933yrcv97nd6pmrt7fzmhs8xxxxx")


def test_ensure_valid_address_nft():
    address = ensure_valid_address(
        "nft1mx2nkvml2eekjtqwdmxvmf3js8g083hpszzhkhtwvhcss8efqzhqtza773", allowed_types={AddressType.NFT}
    )
    assert address == "nft1mx2nkvml2eekjtqwdmxvmf3js8g083hpszzhkhtwvhcss8efqzhqtza773"


def test_ensure_valid_address_nft_bad_address():
    with pytest.raises(ValueError):
        ensure_valid_address(
            "nft1mx2nkvml2eekjtqwdmxvmf3js8g083hpszzhkhtwvhcss8efqzhqtxxxxx", allowed_types={AddressType.NFT}
        )


def test_ensure_valid_address_did():
    address = ensure_valid_address(
        "did:chia:14jxdtqcyp3gk8ka0678eq8mmtnktgpmp2vuqq3vtsl2e5qr7fyrsr9gsr7", allowed_types={AddressType.DID}
    )
    assert address == "did:chia:14jxdtqcyp3gk8ka0678eq8mmtnktgpmp2vuqq3vtsl2e5qr7fyrsr9gsr7"


def test_ensure_valid_address_did_bad_address():
    with pytest.raises(ValueError):
        ensure_valid_address(
            "did:chia:14jxdtqcyp3gk8ka0678eq8mmtnktgpmp2vuqq3vtsl2e5qr7fyrsrxxxxx", allowed_types={AddressType.DID}
        )
