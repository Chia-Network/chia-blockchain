import logging
import clvm
import json

from blspy import ExtendedPrivateKey
from dataclasses import dataclass
from secrets import token_bytes
from typing import Dict, Optional, List, Tuple, Any, Set

from src.server.server import ChiaServer
from src.types.BLSSignature import BLSSignature
from src.types.coin import Coin
from src.types.coin_solution import CoinSolution
from src.types.program import Program
from src.types.spend_bundle import SpendBundle
from src.types.sized_bytes import bytes32
from src.util.ints import uint64, uint32
from src.util.streamable import streamable, Streamable
from src.wallet.util.wallet_types import WalletType
from src.wallet.wallet import Wallet
from src.wallet.wallet_coin_record import WalletCoinRecord
from src.wallet.wallet_info import WalletInfo
from src.wallet.derivation_record import DerivationRecord


@dataclass(frozen=True)
@streamable
class CCInfo(Streamable):
    my_cores = Set  # core is stored as a
    my_coloured_coins = Optional[Dict]  # {coin: (innerpuzzle as Program, core as string)}
    eve_coloured_coins = Optional[Dict]
    parent_info = Optional[Dict] # {coin.name(): (parent_coin_info, puzzle_hash, coin.amount)}
    puzzle_cache = Optional[Dict] # {"innerpuz"+"core": puzzle}
    my_cc_puzhashes = Optional[Dict] # {cc_puzhash: (innerpuzzle, core)}


class CCWallet:
    private_key: ExtendedPrivateKey
    key_config: Dict
    config: Dict
    server: Optional[ChiaServer]
    wallet_state_manager: Any
    log: logging.Logger
    wallet_info: WalletInfo
    cc_coin_record: WalletCoinRecord
    cc_info: CCInfo
    standard_wallet: Wallet

    @staticmethod
    async def create(
        config: Dict,
        key_config: Dict,
        wallet_state_manager: Any,
        wallet: Wallet,
        name: str = None,
    ):
        unused: Optional[
            uint32
        ] = await wallet_state_manager.puzzle_store.get_unused_derivation_path()
        if unused is None:
            await wallet_state_manager.create_more_puzzle_hashes()
        unused = await wallet_state_manager.puzzle_store.get_unused_derivation_path()
        assert unused is not None
        self = CCWallet()
        self.config = config
        self.key_config = key_config
        sk_hex = self.key_config["wallet_sk"]
        self.private_key = ExtendedPrivateKey.from_bytes(bytes.fromhex(sk_hex))
        private_key = ExtendedPrivateKey.from_bytes(bytes.fromhex(sk_hex))
        pubkey_bytes: bytes = bytes(private_key.public_child(unused).get_public_key())

        if name:
            self.log = logging.getLogger(name)
        else:
            self.log = logging.getLogger(__name__)

        self.wallet_state_manager = wallet_state_manager

        cc_info = CCInfo(set(), dict(), dict(), dict(), dict(), dict())
        info_as_string = json.dumps(cc_info.to_json_dict())
        await wallet_state_manager.user_store.create_wallet(
            "CC Wallet", WalletType.COLOURED_COIN, info_as_string
        )
        wallet_info = await wallet_state_manager.user_store.get_last_wallet()
        if wallet_info is None:
            raise

        await wallet_state_manager.puzzle_store.add_derivation_paths(
            [
                DerivationRecord(
                    unused,
                    token_bytes(),
                    pubkey_bytes,
                    WalletType.COLOURED_COIN,
                    wallet_info.id,
                )
            ]
        )
        await wallet_state_manager.puzzle_store.set_used_up_to(unused)

        return self
