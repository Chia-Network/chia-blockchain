import logging
import time
import json

from typing import Dict, Optional, List, Any, Set, Tuple
from blspy import AugSchemeMPL, G1Element
from secrets import token_bytes
from chia.protocols import wallet_protocol
from chia.protocols.wallet_protocol import CoinState
from chia.types.announcement import Announcement
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.spend_bundle import SpendBundle
from chia.util.ints import uint64, uint32, uint8
from chia.wallet.util.transaction_type import TransactionType

from chia.wallet.did_wallet.did_info import DIDInfo
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_coin_record import WalletCoinRecord
from chia.wallet.wallet_info import WalletInfo
from chia.wallet.derivation_record import DerivationRecord
from chia.wallet.did_wallet import did_wallet_puzzles
from chia.wallet.derive_keys import master_sk_to_wallet_sk_unhardened


class NFTCoinInfo:
    minter: bytes32
    creator_fee: Optional[uint64]
    fee_puzzle: Optional[Program]


class NFTWalletInfo:
    did_wallet_id: int
    coin_info: List[NFTCoinInfo]


class NFTWallet:
    wallet_state_manager: Any
    log: logging.Logger
    wallet_info: WalletInfo
    did_info: DIDInfo
    standard_wallet: Wallet
    base_puzzle_program: Optional[bytes]
    base_inner_puzzle_hash: Optional[bytes32]
    wallet_id: int

    @staticmethod
    async def create_new_did_wallet(
        wallet_state_manager: Any,
        wallet: Wallet,
        amount: uint64,
        backups_ids: List = [],
        num_of_backup_ids_needed: uint64 = None,
        name: str = None,
    ):
        """
        This must be called under the wallet state manager lock
        """
        self = DIDWallet()
        self.base_puzzle_program = None
        self.base_inner_puzzle_hash = None
        self.standard_wallet = wallet
        self.log = logging.getLogger(name if name else __name__)
        std_wallet_id = self.standard_wallet.wallet_id
        self.wallet_state_manager = wallet_state_manager
        self.did_info = DIDInfo(None, backups_ids, num_of_backup_ids_needed, [], None, None, None, None, False)
        info_as_string = json.dumps(self.did_info.to_json_dict())
        self.wallet_info = await wallet_state_manager.user_store.create_wallet(
            "DID Wallet", WalletType.DISTRIBUTED_ID.value, info_as_string
        )
        if self.wallet_info is None:
            raise ValueError("Internal Error")
        self.wallet_id = self.wallet_info.id
        std_wallet_id = self.standard_wallet.wallet_id
        await self.wallet_state_manager.add_new_wallet(self, self.wallet_info.id)
