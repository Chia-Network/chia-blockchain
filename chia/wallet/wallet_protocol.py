from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional, TypeVar, runtime_checkable

from chia_rs import G1Element, G2Element
from typing_extensions import NotRequired, Protocol, TypedDict, Unpack

from chia.server.ws_connection import WSChiaConnection
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.signing_mode import SigningMode
from chia.util.ints import uint32, uint64, uint128
from chia.util.observation_root import ObservationRoot
from chia.wallet.conditions import Condition
from chia.wallet.derivation_record import DerivationRecord
from chia.wallet.nft_wallet.nft_info import NFTCoinInfo
from chia.wallet.payment import Payment
from chia.wallet.puzzles.clawback.metadata import ClawbackMetadata
from chia.wallet.signer_protocol import (
    PathHint,
    SignedTransaction,
    SigningInstructions,
    SigningResponse,
    Spend,
    SumHint,
)
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet_action_scope import WalletActionScope
from chia.wallet.wallet_coin_record import WalletCoinRecord
from chia.wallet.wallet_info import WalletInfo
from chia.wallet.wallet_spend_bundle import WalletSpendBundle

if TYPE_CHECKING:
    from chia.wallet.wallet_state_manager import WalletStateManager

T = TypeVar("T", contravariant=True)


@runtime_checkable
class WalletProtocol(Protocol[T]):
    @classmethod
    def type(cls) -> WalletType: ...

    def id(self) -> uint32: ...

    async def coin_added(self, coin: Coin, height: uint32, peer: WSChiaConnection, coin_data: Optional[T]) -> None: ...

    async def select_coins(
        self,
        amount: uint64,
        action_scope: WalletActionScope,
    ) -> set[Coin]: ...

    async def get_confirmed_balance(self, record_list: Optional[set[WalletCoinRecord]] = None) -> uint128: ...

    async def get_unconfirmed_balance(self, unspent_records: Optional[set[WalletCoinRecord]] = None) -> uint128: ...

    async def get_spendable_balance(self, unspent_records: Optional[set[WalletCoinRecord]] = None) -> uint128: ...

    async def get_pending_change_balance(self) -> uint64: ...

    async def get_max_send_amount(self, records: Optional[set[WalletCoinRecord]] = None) -> uint128: ...

    # not all wallet supports this. To signal support, make
    # require_derivation_paths() return true
    def puzzle_hash_for_pk(self, pubkey: G1Element) -> bytes32: ...

    def require_derivation_paths(self) -> bool: ...

    def get_name(self) -> str: ...

    async def match_hinted_coin(self, coin: Coin, hint: bytes32) -> bool: ...

    def handle_own_derivation(self) -> bool: ...

    def derivation_for_index(self, index: int) -> list[DerivationRecord]: ...

    wallet_info: WalletInfo
    # WalletStateManager is only imported for type hinting thus leaving pylint
    # unable to process this
    wallet_state_manager: WalletStateManager  # pylint: disable=used-before-assignment


@runtime_checkable
class MainWalletProtocol(WalletProtocol[ClawbackMetadata], Protocol):
    @property
    def max_send_quantity(self) -> int: ...

    @staticmethod
    async def create(
        wallet_state_manager: Any,
        info: WalletInfo,
        name: str = ...,
    ) -> MainWalletProtocol: ...

    async def get_new_puzzle(self) -> Program: ...

    async def get_new_puzzlehash(self) -> bytes32: ...

    # This isn't part of the WalletProtocol but it should be
    # Also this doesn't likely conform to the eventual one that ends up in WalletProtocol
    async def generate_signed_transaction(
        self,
        amount: uint64,
        puzzle_hash: bytes32,
        action_scope: WalletActionScope,
        fee: uint64 = uint64(0),
        coins: Optional[set[Coin]] = None,
        primaries: Optional[list[Payment]] = None,
        memos: Optional[list[bytes]] = None,
        puzzle_decorator_override: Optional[list[dict[str, Any]]] = None,
        extra_conditions: tuple[Condition, ...] = tuple(),
        **kwargs: Unpack[GSTOptionalArgs],
    ) -> None: ...

    def puzzle_for_pk(self, pubkey: ObservationRoot) -> Program: ...

    async def puzzle_for_puzzle_hash(self, puzzle_hash: bytes32) -> Program: ...

    async def sign_message(
        self, message: str, puzzle_hash: bytes32, mode: SigningMode
    ) -> tuple[G1Element, G2Element]: ...

    async def get_puzzle_hash(self, new: bool) -> bytes32: ...

    async def apply_signatures(
        self, spends: list[Spend], signing_responses: list[SigningResponse]
    ) -> SignedTransaction: ...

    async def execute_signing_instructions(
        self, signing_instructions: SigningInstructions, partial_allowed: bool = False
    ) -> list[SigningResponse]: ...

    async def gather_signing_info(self, coin_spends: list[Spend]) -> SigningInstructions: ...

    async def path_hint_for_pubkey(self, pk: bytes) -> Optional[PathHint]: ...

    async def sum_hint_for_pubkey(self, pk: bytes) -> Optional[SumHint]: ...

    async def create_tandem_xch_tx(
        self,
        fee: uint64,
        action_scope: WalletActionScope,
        extra_conditions: tuple[Condition, ...] = tuple(),
    ) -> None: ...

    async def make_solution(
        self,
        primaries: list[Payment],
        action_scope: WalletActionScope,
        conditions: tuple[Condition, ...] = tuple(),
        fee: uint64 = uint64(0),
    ) -> Program: ...

    async def get_puzzle(self, new: bool) -> Program: ...

    async def convert_puzzle_hash(self, puzzle_hash: bytes32) -> bytes32: ...

    async def get_coins_to_offer(
        self,
        asset_id: Optional[bytes32],
        amount: uint64,
        action_scope: WalletActionScope,
    ) -> set[Coin]: ...


class GSTOptionalArgs(TypedDict):
    # DataLayerWallet
    launcher_id: NotRequired[Optional[bytes32]]
    new_root_hash: NotRequired[Optional[bytes32]]
    sign: NotRequired[bool]
    add_pending_singleton: NotRequired[bool]
    announce_new_state: NotRequired[bool]
    # CATWallet
    cat_discrepancy: NotRequired[Optional[tuple[int, Program, Program]]]
    # NFTWallet
    nft_coin: NotRequired[Optional[NFTCoinInfo]]
    new_owner: NotRequired[Optional[bytes]]
    new_did_inner_hash: NotRequired[Optional[bytes]]
    trade_prices_list: NotRequired[Optional[Program]]
    additional_bundles: NotRequired[list[WalletSpendBundle]]
    metadata_update: NotRequired[Optional[tuple[str, str]]]
    # CR-CAT Wallet
    add_authorizations_to_cr_cats: NotRequired[bool]
    # VCWallet
    new_proof_hash: NotRequired[Optional[bytes32]]
    provider_inner_puzhash: NotRequired[Optional[bytes32]]
    self_revoke: NotRequired[bool]
    # Wallet
    origin_id: NotRequired[Optional[bytes32]]
    negative_change_allowed: NotRequired[bool]
