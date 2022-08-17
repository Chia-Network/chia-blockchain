import logging
from pathlib import Path
from typing import Optional

import requests

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.util.hash import std_hash
from chia.wallet.nft_wallet.nft_info import NFTCoinInfo
from chia.wallet.nft_wallet.uncurry_nft import UncurriedNFT

PREFIX_HASH_LENGTH = 3
CACHE_PATH_KEY = "nft_metadata_cache_path"
DEFAULT_PATH = DEFAULT_ROOT_PATH / "nft_cache"
DEFAULT_PATH.mkdir(parents=True, exist_ok=True)
log = logging.getLogger(__name__)


def fetch_off_chain_metadata(nft_coin_info: NFTCoinInfo) -> Optional[str]:
    uncurried_nft: Optional[UncurriedNFT] = UncurriedNFT.uncurry(*nft_coin_info.full_puzzle.uncurry())
    if uncurried_nft is None:
        return None
    for uri in uncurried_nft.meta_uris.as_python():  # pylint: disable=E1133
        response = requests.get(uri)
        if response.status_code == 200:
            return response.text
    return None


def read_off_chain_metadata(nft_coin_info: NFTCoinInfo, cache_path: Optional[str] = None) -> Optional[str]:
    # Read metadata from disk cache
    cache = DEFAULT_PATH
    if cache_path is not None:
        cache = Path(cache_path)
    file_name = cache / nft_coin_info.nft_id.hex()[:PREFIX_HASH_LENGTH] / nft_coin_info.nft_id.hex()
    if not file_name.exists():
        return None
    try:
        text = file_name.read_text()
        if verify_metadata(text, nft_coin_info.full_puzzle):
            return text
        else:
            return None
    except Exception:
        return None


def delete_off_chain_metadata(nft_id: bytes32, cache_path: Optional[str] = None) -> None:
    cache = DEFAULT_PATH
    if cache_path is not None:
        cache = Path(cache_path)
    file_name = cache / nft_id.hex()[:PREFIX_HASH_LENGTH] / nft_id.hex()
    if file_name.exists():
        file_name.unlink()
        log.info(f"Deleted off-chain metadata of {nft_id.hex()}")


def write_off_chain_metadata(cache_path: Optional[str], nft_id: bytes32, metadata: str) -> None:
    cache = DEFAULT_PATH
    if cache_path is not None:
        cache = Path(cache_path)
    folder = cache / nft_id.hex()[:PREFIX_HASH_LENGTH]
    folder.mkdir(parents=True, exist_ok=True)
    file_name = folder / nft_id.hex()
    file_name.write_text(metadata)


def get_off_chain_metadata(nft_coin_info: NFTCoinInfo, cache_path: Optional[str] = None) -> Optional[str]:
    try:
        # Check if the metadata is in disk cache
        metadata = read_off_chain_metadata(nft_coin_info, cache_path)
        if metadata is not None:
            return metadata
        log.debug(f"{nft_coin_info.nft_id.hex()} is not in cache, downloading now ...")
        metadata = fetch_off_chain_metadata(nft_coin_info)
        if metadata is None:
            log.error(f"Cannot find off-chain metadata of {nft_coin_info.nft_id.hex()}.")
            return None
        write_off_chain_metadata(cache_path, nft_coin_info.nft_id, metadata)
        log.info(f"Loaded off-chain metadata of {nft_coin_info.nft_id.hex()}")
        return metadata
    except Exception:
        log.exception(f"Cannot get off-chain metadata of {nft_coin_info.nft_id.hex()}.")
        return None


def verify_metadata(metadata: str, full_puzzle: Program) -> bool:
    uncurried_nft: Optional[UncurriedNFT] = UncurriedNFT.uncurry(*full_puzzle.uncurry())
    if uncurried_nft is None:
        return False
    if uncurried_nft.meta_hash.as_python().hex() == std_hash(str.encode(metadata)).hex():
        return True
    else:
        return False
