from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypeVar

from chia_rs import G1Element
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32, uint64, uint128
from typing_extensions import NotRequired, Protocol, TypedDict, Unpack

from chia.server.ws_connection import WSChiaConnection
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.wallet.conditions import Condition
from chia.wallet.nft_wallet.nft_info import NFTCoinInfo
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet_action_scope import WalletActionScope
from chia.wallet.wallet_coin_record import WalletCoinRecord
from chia.wallet.wallet_info import WalletInfo
from chia.wallet.wallet_spend_bundle import WalletSpendBundle

if TYPE_CHECKING:
    from chia.wallet.wallet_state_manager import WalletStateManager

T_contra = TypeVar("T_contra", contravariant=True)


class WalletProtocol(Protocol[T_contra]):
    @classmethod
    def type(cls) -> WalletType: ...

    def id(self) -> uint32: ...

    async def coin_added(
        self, coin: Coin, height: uint32, peer: WSChiaConnection, coin_data: T_contra | None
    ) -> None: ...

    async def select_coins(
        self,
        amount: uint64,
        action_scope: WalletActionScope,
    ) -> set[Coin]: ...

    async def get_confirmed_balance(self, record_list: set[WalletCoinRecord] | None = None) -> uint128: ...

    async def get_unconfirmed_balance(self, unspent_records: set[WalletCoinRecord] | None = None) -> uint128: ...

    async def get_spendable_balance(self, unspent_records: set[WalletCoinRecord] | None = None) -> uint128: ...

    async def get_pending_change_balance(self) -> uint64: ...

    async def get_max_send_amount(self, records: set[WalletCoinRecord] | None = None) -> uint128: ...

    # not all wallet supports this. To signal support, make
    # require_derivation_paths() return true
    def puzzle_hash_for_pk(self, pubkey: G1Element) -> bytes32: ...

    def require_derivation_paths(self) -> bool: ...

    def get_name(self) -> str: ...

    async def match_hinted_coin(self, coin: Coin, hint: bytes32) -> bool: ...

    async def generate_signed_transaction(
        self,
        amounts: list[uint64],
        puzzle_hashes: list[bytes32],
        action_scope: WalletActionScope,
        fee: uint64 = uint64(0),
        coins: set[Coin] | None = None,
        memos: list[list[bytes]] | None = None,
        extra_conditions: tuple[Condition, ...] = tuple(),
        **kwargs: Unpack[GSTOptionalArgs],
    ) -> None: ...

    wallet_info: WalletInfo
    wallet_state_manager: WalletStateManager


class GSTOptionalArgs(TypedDict):
    # DataLayerWallet
    launcher_id: NotRequired[bytes32 | None]
    new_root_hash: NotRequired[bytes32 | None]
    sign: NotRequired[bool]
    announce_new_state: NotRequired[bool]
    # CATWallet
    cat_discrepancy: NotRequired[tuple[int, Program, Program] | None]
    # NFTWallet
    nft_coin: NotRequired[NFTCoinInfo | None]
    new_owner: NotRequired[bytes | None]
    new_did_inner_hash: NotRequired[bytes | None]
    trade_prices_list: NotRequired[Program | None]
    additional_bundles: NotRequired[list[WalletSpendBundle]]
    metadata_update: NotRequired[tuple[str, str] | None]
    # CR-CAT Wallet
    add_authorizations_to_cr_cats: NotRequired[bool]
    # VCWallet
    new_proof_hash: NotRequired[bytes32 | None]
    provider_inner_puzhash: NotRequired[bytes32 | None]
    self_revoke: NotRequired[bool]
    vc_id: NotRequired[bytes32 | None]
    # Wallet
    origin_id: NotRequired[bytes32 | None]
    negative_change_allowed: NotRequired[bool]
    puzzle_decorator_override: NotRequired[list[dict[str, Any]] | None]
    reserve_fee: NotRequired[uint64 | None]
    preferred_change_puzzle_hash: NotRequired[bytes32 | None]
