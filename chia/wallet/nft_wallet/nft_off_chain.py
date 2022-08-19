import logging
import sys
from pathlib import Path
from typing import Optional

import aiohttp

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.util.hash import std_hash
from chia.wallet.nft_wallet.nft_info import NFTCoinInfo
from chia.wallet.nft_wallet.uncurry_nft import UncurriedNFT

PREFIX_HASH_LENGTH = 3
CACHE_PATH_KEY = "nft_metadata_cache_path"
DEFAULT_PATH = DEFAULT_ROOT_PATH / "nft_cache"

log = logging.getLogger(__name__)


async def fetch_off_chain_metadata(nft_coin_info: NFTCoinInfo, ignore_size_limit: bool) -> Optional[str]:
    uncurried_nft: Optional[UncurriedNFT] = UncurriedNFT.uncurry(*nft_coin_info.full_puzzle.uncurry())
    if uncurried_nft is None:
        log.error(f"Cannot fetch off-chain metadata, {nft_coin_info.nft_id} is not a NFT.")
        return None
    for uri in uncurried_nft.meta_uris.as_python():  # pylint: disable=E1133
        async with aiohttp.ClientSession() as session:
            async with session.get(str(uri, "utf-8")) as response:
                if response.status == 200:
                    text = await response.text()
                    if ignore_size_limit or sys.getsizeof(text) / 1024 / 1024 < 1:
                        return text
    return None


def read_off_chain_metadata(nft_coin_info: NFTCoinInfo, cache_path: Optional[str] = None) -> Optional[str]:
    # Read metadata from disk cache
    file_name = get_cached_filename(nft_coin_info.nft_id, cache_path)
    if not file_name.exists():
        return None
    try:
        text = file_name.read_text()
        if verify_metadata(text, nft_coin_info.full_puzzle):
            return text
        else:
            return None
    except Exception:
        log.exception(f"Cannot load cached metadata of {nft_coin_info.nft_id.hex()}.")
        return None


def delete_off_chain_metadata(nft_id: bytes32, cache_path: Optional[str] = None) -> None:
    file_name = get_cached_filename(nft_id, cache_path)
    if file_name.exists():
        file_name.unlink()
        log.info(f"Deleted off-chain metadata of {nft_id.hex()}")


def write_off_chain_metadata(cache_path: Optional[str], nft_id: bytes32, metadata: str) -> None:
    file_name = get_cached_filename(nft_id, cache_path)
    file_name.write_text(metadata)


async def get_off_chain_metadata(
    nft_coin_info: NFTCoinInfo, cache_path: Optional[str] = None, ignore_size_limit: bool = False
) -> Optional[str]:
    try:
        # Check if the metadata is in disk cache
        metadata = read_off_chain_metadata(nft_coin_info, cache_path)
        if metadata is not None:
            return metadata
        log.debug(f"{nft_coin_info.nft_id.hex()} is not in cache, downloading now ...")
        metadata = await fetch_off_chain_metadata(nft_coin_info, ignore_size_limit)
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
        log.error(
            f"Expect metadata hash: {uncurried_nft.meta_hash.as_python().hex()},"
            f" actual metadata hash {std_hash(str.encode(metadata)).hex()}"
        )
        return False


def get_cached_filename(nft_id: bytes32, cache_path: Optional[str] = None) -> Path:
    if not DEFAULT_PATH.exists():
        DEFAULT_PATH.mkdir(parents=True, exist_ok=True)
    cache = DEFAULT_PATH
    if cache_path is not None and cache_path != "":
        cache = Path(cache_path)
    folder = cache / nft_id.hex()[:PREFIX_HASH_LENGTH]
    folder.mkdir(parents=True, exist_ok=True)
    return folder / nft_id.hex()
