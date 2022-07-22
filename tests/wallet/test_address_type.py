from pathlib import Path
from typing import Any, Dict, Tuple

import pytest

from chia.wallet.util.address_type import AddressType, ensure_valid_address, is_valid_address


@pytest.mark.parametrize("prefix", [None])
def test_current_network_address_type_default_config(
    root_path_and_config_with_address_prefix: Tuple[Path, Dict[str, Any]]
) -> None:
    root_path = root_path_and_config_with_address_prefix[0]
    assert AddressType.current_network_address_type(root_path=root_path).value == "xch"


@pytest.mark.parametrize("prefix", ["txch"])
def test_current_network_address_type_testnet_config(
    root_path_and_config_with_address_prefix: Tuple[Path, Dict[str, Any]]
) -> None:
    config = root_path_and_config_with_address_prefix[1]
    assert AddressType.current_network_address_type(config=config).value == "txch"


def test_is_valid_address_xch() -> None:
    valid = is_valid_address(
        "xch1mnr0ygu7lvmk3nfgzmncfk39fwu0dv933yrcv97nd6pmrt7fzmhs8taffd", allowed_types={AddressType.XCH}
    )
    assert valid is True


def test_is_valid_address_txch() -> None:
    valid = is_valid_address(
        "txch1mnr0ygu7lvmk3nfgzmncfk39fwu0dv933yrcv97nd6pmrt7fzmhs2v6lg7", allowed_types={AddressType.TXCH}
    )
    assert valid is True


def test_is_valid_address_xch_bad_address() -> None:
    valid = is_valid_address(
        "xch1mnr0ygu7lvmk3nfgzmncfk39fwu0dv933yrcv97nd6pmrt7fzmhs8xxxxx", allowed_types={AddressType.XCH}
    )
    assert valid is False


def test_is_valid_address_nft() -> None:
    valid = is_valid_address(
        "nft1mx2nkvml2eekjtqwdmxvmf3js8g083hpszzhkhtwvhcss8efqzhqtza773", allowed_types={AddressType.NFT}
    )
    assert valid is True


def test_is_valid_address_nft_bad_address() -> None:
    valid = is_valid_address(
        "nft1mx2nkvml2eekjtqwdmxvmf3js8g083hpszzhkhtwvhcss8efqzhqtxxxxx", allowed_types={AddressType.NFT}
    )
    assert valid is False


def test_is_valid_address_did() -> None:
    valid = is_valid_address(
        "did:chia:14jxdtqcyp3gk8ka0678eq8mmtnktgpmp2vuqq3vtsl2e5qr7fyrsr9gsr7", allowed_types={AddressType.DID}
    )
    assert valid is True


def test_is_valid_address_did_bad_address() -> None:
    valid = is_valid_address(
        "did:chia:14jxdtqcyp3gk8ka0678eq8mmtnktgpmp2vuqq3vtsl2e5qr7fyrsrxxxxx", allowed_types={AddressType.DID}
    )
    assert valid is False


def test_ensure_valid_address_xch() -> None:
    address = ensure_valid_address(
        "xch1mnr0ygu7lvmk3nfgzmncfk39fwu0dv933yrcv97nd6pmrt7fzmhs8taffd", allowed_types={AddressType.XCH}
    )
    assert address == "xch1mnr0ygu7lvmk3nfgzmncfk39fwu0dv933yrcv97nd6pmrt7fzmhs8taffd"


def test_ensure_valid_address_txch() -> None:
    address = ensure_valid_address(
        "txch1mnr0ygu7lvmk3nfgzmncfk39fwu0dv933yrcv97nd6pmrt7fzmhs2v6lg7", allowed_types={AddressType.TXCH}
    )
    assert address == "txch1mnr0ygu7lvmk3nfgzmncfk39fwu0dv933yrcv97nd6pmrt7fzmhs2v6lg7"


def test_ensure_valid_address_xch_bad_address() -> None:
    with pytest.raises(ValueError):
        ensure_valid_address(
            "xch1mnr0ygu7lvmk3nfgzmncfk39fwu0dv933yrcv97nd6pmrt7fzmhs8xxxxx", allowed_types={AddressType.XCH}
        )


def test_ensure_valid_address_nft() -> None:
    address = ensure_valid_address(
        "nft1mx2nkvml2eekjtqwdmxvmf3js8g083hpszzhkhtwvhcss8efqzhqtza773", allowed_types={AddressType.NFT}
    )
    assert address == "nft1mx2nkvml2eekjtqwdmxvmf3js8g083hpszzhkhtwvhcss8efqzhqtza773"


def test_ensure_valid_address_nft_bad_address() -> None:
    with pytest.raises(ValueError):
        ensure_valid_address(
            "nft1mx2nkvml2eekjtqwdmxvmf3js8g083hpszzhkhtwvhcss8efqzhqtxxxxx", allowed_types={AddressType.NFT}
        )


def test_ensure_valid_address_did() -> None:
    address = ensure_valid_address(
        "did:chia:14jxdtqcyp3gk8ka0678eq8mmtnktgpmp2vuqq3vtsl2e5qr7fyrsr9gsr7", allowed_types={AddressType.DID}
    )
    assert address == "did:chia:14jxdtqcyp3gk8ka0678eq8mmtnktgpmp2vuqq3vtsl2e5qr7fyrsr9gsr7"


def test_ensure_valid_address_did_bad_address() -> None:
    with pytest.raises(ValueError):
        ensure_valid_address(
            "did:chia:14jxdtqcyp3gk8ka0678eq8mmtnktgpmp2vuqq3vtsl2e5qr7fyrsrxxxxx", allowed_types={AddressType.DID}
        )


def test_ensure_valid_address_bad_length() -> None:
    with pytest.raises(ValueError):
        ensure_valid_address("xch1qqqqqqqqqqqqqqqqwygzk5", allowed_types={AddressType.XCH})
