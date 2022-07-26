from pathlib import Path
from typing import Any, Dict, Tuple

import pytest

from chia.wallet.util.address_type import AddressType, ensure_valid_address, is_valid_address


@pytest.mark.parametrize("prefix", [None])
def test_xch_hrp_for_default_config(root_path_and_config_with_address_prefix: Tuple[Path, Dict[str, Any]]) -> None:
    config = root_path_and_config_with_address_prefix[1]
    assert AddressType.XCH.hrp(config) == "xch"


@pytest.mark.parametrize("prefix", ["txch"])
def test_txch_hrp_for_testnet_config(root_path_and_config_with_address_prefix: Tuple[Path, Dict[str, Any]]) -> None:
    config = root_path_and_config_with_address_prefix[1]
    assert AddressType.XCH.hrp(config) == "txch"


def test_hrps_no_config() -> None:
    assert AddressType.XCH.hrp() == "xch"
    assert AddressType.NFT.hrp() == "nft"
    assert AddressType.DID.hrp() == "did:chia:"


@pytest.mark.parametrize("prefix", [None])
def test_is_valid_address_xch_with_config(
    root_path_and_config_with_address_prefix: Tuple[Path, Dict[str, Any]]
) -> None:
    config = root_path_and_config_with_address_prefix[1]
    valid = is_valid_address(
        "xch1mnr0ygu7lvmk3nfgzmncfk39fwu0dv933yrcv97nd6pmrt7fzmhs8taffd", allowed_types={AddressType.XCH}, config=config
    )
    assert valid is True


def test_is_valid_address_xch_no_config() -> None:
    valid = is_valid_address(
        "xch1mnr0ygu7lvmk3nfgzmncfk39fwu0dv933yrcv97nd6pmrt7fzmhs8taffd", allowed_types={AddressType.XCH}
    )
    assert valid is True


@pytest.mark.parametrize("prefix", ["txch"])
def test_is_valid_address_txch_with_config(
    root_path_and_config_with_address_prefix: Tuple[Path, Dict[str, Any]]
) -> None:
    config = root_path_and_config_with_address_prefix[1]
    # TXCH address validation requires a config
    valid = is_valid_address(
        "txch1mnr0ygu7lvmk3nfgzmncfk39fwu0dv933yrcv97nd6pmrt7fzmhs2v6lg7",
        allowed_types={AddressType.XCH},
        config=config,
    )
    assert valid is True


def test_is_valid_address_txch_no_config() -> None:
    # TXCH address validation requires a config, so valid should be False
    valid = is_valid_address(
        "txch1mnr0ygu7lvmk3nfgzmncfk39fwu0dv933yrcv97nd6pmrt7fzmhs2v6lg7", allowed_types={AddressType.XCH}
    )
    assert valid is False


def test_is_valid_address_xch_bad_address() -> None:
    valid = is_valid_address(
        "xch1mnr0ygu7lvmk3nfgzmncfk39fwu0dv933yrcv97nd6pmrt7fzmhs8xxxxx", allowed_types={AddressType.XCH}
    )
    assert valid is False


@pytest.mark.parametrize("prefix", [None])
def test_is_valid_address_nft_with_config(
    root_path_and_config_with_address_prefix: Tuple[Path, Dict[str, Any]]
) -> None:
    config = root_path_and_config_with_address_prefix[1]
    valid = is_valid_address(
        "nft1mx2nkvml2eekjtqwdmxvmf3js8g083hpszzhkhtwvhcss8efqzhqtza773", allowed_types={AddressType.NFT}, config=config
    )
    assert valid is True


@pytest.mark.parametrize("prefix", ["txch"])
def test_is_valid_address_nft_with_testnet_config(
    root_path_and_config_with_address_prefix: Tuple[Path, Dict[str, Any]]
) -> None:
    config = root_path_and_config_with_address_prefix[1]
    valid = is_valid_address(
        "nft1mx2nkvml2eekjtqwdmxvmf3js8g083hpszzhkhtwvhcss8efqzhqtza773", allowed_types={AddressType.NFT}, config=config
    )
    assert valid is True


def test_is_valid_address_nft_no_config() -> None:
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


@pytest.mark.parametrize("prefix", ["txch"])
def test_ensure_valid_address_txch(root_path_and_config_with_address_prefix: Tuple[Path, Dict[str, Any]]) -> None:
    config = root_path_and_config_with_address_prefix[1]
    address = ensure_valid_address(
        "txch1mnr0ygu7lvmk3nfgzmncfk39fwu0dv933yrcv97nd6pmrt7fzmhs2v6lg7",
        allowed_types={AddressType.XCH},
        config=config,
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
