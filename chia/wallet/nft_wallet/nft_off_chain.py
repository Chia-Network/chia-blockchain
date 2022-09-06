import logging
import re
from pathlib import Path
from typing import Any, Dict, Optional

import aiohttp

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.util.hash import std_hash
from chia.util.path import path_from_root
from chia.wallet.nft_wallet.nft_info import NFTCoinInfo
from chia.wallet.nft_wallet.uncurry_nft import UncurriedNFT

DEFAULT_PREFIX_HASH_LENGTH = 3
DEFAULT_CACHE_PATH = "nft_cache"
CACHE_PATH_KEY = "nft_metadata_cache_path"
PREFIX_HASH_LENGTH_KEY = "nft_metadata_cache_hash_length"


log = logging.getLogger(__name__)


async def fetch_off_chain_metadata(nft_coin_info: NFTCoinInfo, ignore_size_limit: bool) -> Optional[str]:
    uncurried_nft: Optional[UncurriedNFT] = UncurriedNFT.uncurry(*nft_coin_info.full_puzzle.uncurry())
    if uncurried_nft is None:
        log.error(f"Cannot fetch off-chain metadata, {nft_coin_info.nft_id} is not a NFT.")
        return None
    timeout = aiohttp.ClientTimeout(total=30)
    for uri in uncurried_nft.meta_uris.as_python():  # pylint: disable=E1133
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(str(uri, "utf-8")) as response:
                if response.status == 200:
                    text = ""
                    chunk_num = 0
                    async for chunk in response.content.iter_chunked(1024 * 1024):
                        text += str(chunk, "utf-8")
                        chunk_num += 1
                        if chunk_num > 10 and not ignore_size_limit:
                            raise ValueError(f"Off-chain metadata size is too big, NFT_ID:{nft_coin_info.nft_id.hex()}")
                    return text
    return None


def read_off_chain_metadata(nft_coin_info: NFTCoinInfo, config: Optional[Dict[str, Any]] = None) -> Optional[str]:
    # Read metadata from disk cache
    file_name = get_cached_filename(nft_coin_info.nft_id, config)
    if not file_name.exists():
        return None
    try:
        text = file_name.read_text()
        if verify_metadata(text, nft_coin_info.full_puzzle):
            return text
        else:
            log.warning(f"Invalid cached metadata, NFT ID: {nft_coin_info.nft_id.hex()}")
            return None
    except Exception:
        log.exception(f"Cannot load cached metadata of {nft_coin_info.nft_id.hex()}.")
        return None


def delete_off_chain_metadata(nft_id: bytes32, config: Optional[Dict[str, Any]] = None) -> None:
    file_name = get_cached_filename(nft_id, config)
    try:
        file_name.unlink()
        log.info(f"Deleted off-chain metadata of {nft_id.hex()}")
    except Exception:
        log.exception(f"Cannot delete off-chain metadata of {nft_id.hex()}")


def write_off_chain_metadata(nft_id: bytes32, metadata: str, config: Optional[Dict[str, Any]] = None) -> None:
    file_name = get_cached_filename(nft_id, config)
    file_name.write_text(metadata)


async def get_off_chain_metadata(
    nft_coin_info: NFTCoinInfo, config: Optional[Dict[str, Any]] = None, ignore_size_limit: bool = False
) -> Optional[str]:
    try:
        # Check if the metadata is in disk cache
        metadata = read_off_chain_metadata(nft_coin_info, config)
        if metadata is not None:
            return metadata
        log.debug(f"{nft_coin_info.nft_id.hex()} is not in cache, downloading now ...")
        metadata = await fetch_off_chain_metadata(nft_coin_info, ignore_size_limit)
        if metadata is None:
            log.error(f"Cannot find off-chain metadata of {nft_coin_info.nft_id.hex()}.")
            return None
        write_off_chain_metadata(nft_coin_info.nft_id, metadata, config)
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


def get_cached_filename(nft_id: bytes32, config: Optional[Dict[str, Any]]) -> Path:
    cache_path: str = DEFAULT_CACHE_PATH
    hash_length: int = DEFAULT_PREFIX_HASH_LENGTH
    if config is not None:
        cache_path = config.get(CACHE_PATH_KEY, DEFAULT_CACHE_PATH)
        hash_length = config.get(PREFIX_HASH_LENGTH_KEY, DEFAULT_PREFIX_HASH_LENGTH)
    if re.match("^(/.*)|([a-zA-z]:.*)", cache_path):
        cache = Path(cache_path)
    else:
        cache = path_from_root(DEFAULT_ROOT_PATH, cache_path)

    folder = cache / nft_id.hex()[:hash_length]
    folder.mkdir(parents=True, exist_ok=True)
    return folder / nft_id.hex()
