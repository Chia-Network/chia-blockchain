import logging
import time

import clvm
from typing import Dict, Optional, List, Any, Set
from clvm_tools import binutils
from clvm.EvalError import EvalError
from src.types.BLSSignature import BLSSignature
from src.types.coin import Coin
from src.types.coin_solution import CoinSolution
from src.types.condition_opcodes import ConditionOpcode
from src.types.program import Program
from src.types.spend_bundle import SpendBundle
from src.types.sized_bytes import bytes32
from src.util.byte_types import hexstr_to_bytes
from src.util.condition_tools import (
    conditions_dict_for_solution,
    hash_key_pairs_for_conditions_dict,
)
from src.util.json_util import dict_to_json_str
from src.util.ints import uint64, uint32
from src.wallet.BLSPrivateKey import BLSPrivateKey
from src.wallet.block_record import BlockRecord
from src.wallet.did_wallet.did_info import DIDInfo

from src.wallet.transaction_record import TransactionRecord
from src.wallet.util.wallet_types import WalletType
from src.wallet.wallet import Wallet
from src.wallet.wallet_coin_record import WalletCoinRecord
from src.wallet.wallet_info import WalletInfo
from src.wallet.derivation_record import DerivationRecord
from src.wallet.did_wallet import did_puzzle
from clvm import run_program


class DIDWallet:
    wallet_state_manager: Any
    log: logging.Logger
    wallet_info: WalletInfo
    did_info: DIDInfo
    standard_wallet: Wallet
    base_puzzle_program: Optional[bytes]
    base_inner_puzzle_hash: Optional[bytes32]

    @staticmethod
    async def create_new_did(
        wallet_state_manager: Any, wallet: Wallet, name: str = None,
    ):
        self = DIDWallet()
        self.base_puzzle_program = None
        self.base_inner_puzzle_hash = None
        self.standard_wallet = wallet
        if name:
            self.log = logging.getLogger(name)
        else:
            self.log = logging.getLogger(__name__)

        self.wallet_state_manager = wallet_state_manager

        self.did_info = DIDInfo(None)
        info_as_string = bytes(self.did_info).hex()
        self.wallet_info = await wallet_state_manager.user_store.create_wallet(
            "DID Wallet", WalletType.DISTRIBUTED_ID, info_as_string
        )
        if self.wallet_info is None:
            raise ValueError("Internal Error")

        await self.wallet_state_manager.add_new_wallet(self, self.wallet_info.id)

        return self

    @staticmethod
    async def create(
        wallet_state_manager: Any,
        wallet: Wallet,
        wallet_info: WalletInfo,
        name: str = None,
    ):
        self = DIDWallet()

        if name:
            self.log = logging.getLogger(name)
        else:
            self.log = logging.getLogger(__name__)

        self.wallet_state_manager = wallet_state_manager
        self.wallet_info = wallet_info
        self.standard_wallet = wallet
        self.cc_info = DIDInfo.from_bytes(hexstr_to_bytes(self.wallet_info.data))
        self.base_puzzle_program = None
        self.base_inner_puzzle_hash = None
        return self
