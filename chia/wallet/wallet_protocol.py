from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple, TypeVar

from chia_rs import G1Element, G2Element
from typing_extensions import NotRequired, Protocol, TypedDict, Unpack

from chia.server.ws_connection import WSChiaConnection
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.signing_mode import SigningMode
from chia.types.spend_bundle import SpendBundle
from chia.util.ints import uint32, uint64, uint128
from chia.wallet.conditions import Condition
from chia.wallet.nft_wallet.nft_info import NFTCoinInfo
from chia.wallet.payment import Payment
from chia.wallet.puzzles.clawback.metadata import ClawbackMetadata
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.signer_protocol import (
    PathHint,
    SignedTransaction,
    SigningInstructions,
    SigningResponse,
    Spend,
    SumHint,
)
from chia.wallet.util.tx_config import CoinSelectionConfig, TXConfig
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet_coin_record import WalletCoinRecord
from chia.wallet.wallet_info import WalletInfo

if TYPE_CHECKING:
    from chia.wallet.wallet_state_manager import WalletStateManager

T = TypeVar("T", contravariant=True)


class WalletProtocol(Protocol[T]):
    @classmethod
    def type(cls) -> WalletType:
        ...

    def id(self) -> uint32:
        ...

    async def coin_added(self, coin: Coin, height: uint32, peer: WSChiaConnection, coin_data: Optional[T]) -> None:
        ...

    async def select_coins(
        self,
        amount: uint64,
        coin_selection_config: CoinSelectionConfig,
    ) -> Set[Coin]:
        ...

    async def get_confirmed_balance(self, record_list: Optional[Set[WalletCoinRecord]] = None) -> uint128:
        ...

    async def get_unconfirmed_balance(self, unspent_records: Optional[Set[WalletCoinRecord]] = None) -> uint128:
        ...

    async def get_spendable_balance(self, unspent_records: Optional[Set[WalletCoinRecord]] = None) -> uint128:
        ...

    async def get_pending_change_balance(self) -> uint64:
        ...

    async def get_max_send_amount(self, records: Optional[Set[WalletCoinRecord]] = None) -> uint128:
        ...

    # not all wallet supports this. To signal support, make
    # require_derivation_paths() return true
    def puzzle_hash_for_pk(self, pubkey: G1Element) -> bytes32:
        ...

    def require_derivation_paths(self) -> bool:
        ...

    def get_name(self) -> str:
        ...

    async def match_hinted_coin(self, coin: Coin, hint: bytes32) -> bool:
        ...

    wallet_info: WalletInfo
    # WalletStateManager is only imported for type hinting thus leaving pylint
    # unable to process this
    wallet_state_manager: WalletStateManager  # pylint: disable=used-before-assignment


class MainWalletProtocol(WalletProtocol[ClawbackMetadata], Protocol):
    @property
    def max_send_quantity(self) -> int:
        ...

    @staticmethod
    async def create(
        wallet_state_manager: Any,
        info: WalletInfo,
        name: str = ...,
    ) -> MainWalletProtocol:
        ...

    async def get_new_puzzle(self) -> Program:
        ...

    async def get_new_puzzlehash(self) -> bytes32:
        ...

    # This isn't part of the WalletProtocol but it should be
    # Also this doesn't likely conform to the eventual one that ends up in WalletProtocol
    async def generate_signed_transaction(
        self,
        amount: uint64,
        puzzle_hash: bytes32,
        tx_config: TXConfig,
        fee: uint64 = uint64(0),
        coins: Optional[Set[Coin]] = None,
        primaries: Optional[List[Payment]] = None,
        memos: Optional[List[bytes]] = None,
        puzzle_decorator_override: Optional[List[Dict[str, Any]]] = None,
        extra_conditions: Tuple[Condition, ...] = tuple(),
        **kwargs: Unpack[GSTOptionalArgs],
    ) -> List[TransactionRecord]:
        ...

    def puzzle_for_pk(self, pubkey: G1Element) -> Program:
        ...

    async def puzzle_for_puzzle_hash(self, puzzle_hash: bytes32) -> Program:
        ...

    async def sign_message(self, message: str, puzzle_hash: bytes32, mode: SigningMode) -> Tuple[G1Element, G2Element]:
        ...

    async def get_puzzle_hash(self, new: bool) -> bytes32:
        ...

    async def apply_signatures(
        self, spends: List[Spend], signing_responses: List[SigningResponse]
    ) -> SignedTransaction:
        ...

    async def execute_signing_instructions(
        self, signing_instructions: SigningInstructions, partial_allowed: bool = False
    ) -> List[SigningResponse]:
        ...

    async def path_hint_for_pubkey(self, pk: bytes) -> Optional[PathHint]:
        ...

    async def sum_hint_for_pubkey(self, pk: bytes) -> Optional[SumHint]:
        ...

    async def create_tandem_xch_tx(
        self,
        fee: uint64,
        tx_config: TXConfig,
        extra_conditions: Tuple[Condition, ...] = tuple(),
    ) -> TransactionRecord:
        ...

    def make_solution(
        self,
        primaries: List[Payment],
        conditions: Tuple[Condition, ...] = tuple(),
        fee: uint64 = uint64(0),
    ) -> Program:
        ...

    async def get_puzzle(self, new: bool) -> Program:
        ...


class GSTOptionalArgs(TypedDict):
    # DataLayerWallet
    launcher_id: NotRequired[Optional[bytes32]]
    new_root_hash: NotRequired[Optional[bytes32]]
    sign: NotRequired[bool]
    add_pending_singleton: NotRequired[bool]
    announce_new_state: NotRequired[bool]
    # CATWallet
    cat_discrepancy: NotRequired[Optional[Tuple[int, Program, Program]]]
    # NFTWallet
    nft_coin: NotRequired[Optional[NFTCoinInfo]]
    new_owner: NotRequired[Optional[bytes]]
    new_did_inner_hash: NotRequired[Optional[bytes]]
    trade_prices_list: NotRequired[Optional[Program]]
    additional_bundles: NotRequired[List[SpendBundle]]
    metadata_update: NotRequired[Optional[Tuple[str, str]]]
    # CR-CAT Wallet
    add_authorizations_to_cr_cats: NotRequired[bool]
    # VCWallet
    new_proof_hash: NotRequired[Optional[bytes32]]
    provider_inner_puzhash: NotRequired[Optional[bytes32]]
    self_revoke: NotRequired[bool]
    # Wallet
    origin_id: NotRequired[Optional[bytes32]]
    negative_change_allowed: NotRequired[bool]
