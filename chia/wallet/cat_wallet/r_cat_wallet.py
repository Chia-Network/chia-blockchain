from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import IntEnum
from typing import TYPE_CHECKING, Any, Optional

from chia_rs import G1Element
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint16, uint32, uint64
from typing_extensions import Self

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.util.byte_types import hexstr_to_bytes
from chia.util.streamable import Streamable, streamable
from chia.wallet.cat_wallet.cat_constants import DEFAULT_CATS
from chia.wallet.cat_wallet.cat_info import CATCoinData, RCATInfo
from chia.wallet.cat_wallet.cat_utils import (
    CAT_MOD,
    CAT_MOD_HASH,
    CAT_MOD_HASH_HASH,
    QUOTED_CAT_MOD_HASH,
    construct_cat_puzzle,
)
from chia.wallet.cat_wallet.cat_wallet import CATWallet
from chia.wallet.cat_wallet.lineage_store import CATLineageStore
from chia.wallet.conditions import (
    Condition,
    CreateCoin,
)
from chia.wallet.derivation_record import DerivationRecord
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.outer_puzzles import AssetType
from chia.wallet.puzzle_drivers import PuzzleInfo
from chia.wallet.util.curry_and_treehash import curry_and_treehash
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.vc_wallet.vc_drivers import create_revocation_layer, solve_revocation_layer
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_action_scope import WalletActionScope
from chia.wallet.wallet_coin_record import MetadataTypes, WalletCoinRecord
from chia.wallet.wallet_info import WalletInfo
from chia.wallet.wallet_protocol import WalletProtocol

if TYPE_CHECKING:
    from chia.wallet.wallet_state_manager import WalletStateManager


class RCATVersion(IntEnum):
    V1 = uint16(1)


@streamable
@dataclass(frozen=True)
class RCATMetadata(Streamable):
    lineage_proof: LineageProof
    inner_puzzle_hash: bytes32


class RCATWallet(CATWallet):
    wallet_state_manager: WalletStateManager
    log: logging.Logger
    wallet_info: WalletInfo
    cat_info: RCATInfo
    standard_wallet: Wallet
    lineage_store: CATLineageStore

    @property
    def cost_of_single_tx(self) -> int:
        return 78000000  # Estimate measured in testing

    @staticmethod
    async def create_new_cat_wallet(
        wallet_state_manager: WalletStateManager,
        wallet: Wallet,
        cat_tail_info: dict[str, Any],
        amount: uint64,
        action_scope: WalletActionScope,
        fee: uint64 = uint64(0),
        name: Optional[str] = None,
        push: bool = False,
    ) -> CATWallet:  # pragma: no cover
        raise NotImplementedError("create_new_cat_wallet is a legacy method and is not available on R-CAT wallets")

    # We need to override this with a different signature.
    # It's not immediately clear what is proper here, likely needs a bit of a refactor.
    @classmethod
    async def get_or_create_wallet_for_cat(  # type: ignore[override]
        cls,
        wallet_state_manager: WalletStateManager,
        wallet: Wallet,
        limitations_program_hash_hex: str,
        hidden_puzzle_hash: bytes32,
        name: Optional[str] = None,
    ) -> Self:
        self = cls()
        self.standard_wallet = wallet
        self.log = logging.getLogger(__name__)

        limitations_program_hash_hex = bytes32.from_hexstr(limitations_program_hash_hex).hex()  # Normalize the format

        for id, w in wallet_state_manager.wallets.items():
            if w.type() == cls.type():
                assert isinstance(w, cls)
                if w.get_asset_id() == limitations_program_hash_hex:
                    self.log.warning("Not creating wallet for already existing CAT wallet")
                    return w

        self.wallet_state_manager = wallet_state_manager
        if limitations_program_hash_hex in DEFAULT_CATS:
            cat_info = DEFAULT_CATS[limitations_program_hash_hex]
            name = cat_info["name"]
        elif name is None:
            name = self.default_wallet_name_for_unknown_cat(limitations_program_hash_hex)

        limitations_program_hash = bytes32.from_hexstr(limitations_program_hash_hex)
        self.cat_info = RCATInfo(limitations_program_hash, None, hidden_puzzle_hash)
        info_as_string = bytes(self.cat_info).hex()
        self.wallet_info = await wallet_state_manager.user_store.create_wallet(name, WalletType.RCAT, info_as_string)

        self.lineage_store = await CATLineageStore.create(self.wallet_state_manager.db_wrapper, self.get_asset_id())
        # Inherited from duplicating parent
        await self.wallet_state_manager.add_new_wallet(self)

        delete: bool = False
        for state in await self.wallet_state_manager.interested_store.get_unacknowledged_states_for_asset_id(
            limitations_program_hash
        ):
            new_peer = self.wallet_state_manager.wallet_node.get_full_node_peer()
            if new_peer is not None:
                delete = True
                peer_id: bytes32 = new_peer.peer_node_id
                await self.wallet_state_manager.retry_store.add_state(state[0], peer_id, state[1])

        if delete:
            await self.wallet_state_manager.interested_store.delete_unacknowledged_states_for_asset_id(
                limitations_program_hash
            )

        return self

    @classmethod
    async def create_from_puzzle_info(
        cls,
        wallet_state_manager: WalletStateManager,
        wallet: Wallet,
        puzzle_driver: PuzzleInfo,
        name: Optional[str] = None,
        # We're hinting this as Any for mypy by should explore adding this to the wallet protocol and hinting properly
        potential_subclasses: dict[AssetType, Any] = {},
    ) -> Any:
        rev_layer: Optional[PuzzleInfo] = puzzle_driver.also()
        if rev_layer is None:  # pragma: no cover
            raise ValueError("create_from_puzzle_info called on RCATWallet with a non R-CAT puzzle driver")
        return await cls.get_or_create_wallet_for_cat(
            wallet_state_manager,
            wallet,
            puzzle_driver["tail"].hex(),
            bytes32(rev_layer["hidden_puzzle_hash"]),
            name,
        )

    @staticmethod
    async def create(
        wallet_state_manager: WalletStateManager,
        wallet: Wallet,
        wallet_info: WalletInfo,
    ) -> RCATWallet:
        self = RCATWallet()

        self.log = logging.getLogger(__name__)

        self.wallet_state_manager = wallet_state_manager
        self.wallet_info = wallet_info
        self.standard_wallet = wallet
        self.cat_info = RCATInfo.from_bytes(hexstr_to_bytes(self.wallet_info.data))
        self.lineage_store = await CATLineageStore.create(self.wallet_state_manager.db_wrapper, self.get_asset_id())
        return self

    @classmethod
    def type(cls) -> WalletType:
        return WalletType.RCAT

    def id(self) -> uint32:
        return self.wallet_info.id

    def get_asset_id(self) -> str:
        return self.cat_info.limitations_program_hash.hex()

    def puzzle_for_pk(self, pubkey: G1Element) -> Program:
        inner_puzzle = create_revocation_layer(
            self.cat_info.hidden_puzzle_hash, self.standard_wallet.puzzle_hash_for_pk(pubkey)
        )
        cat_puzzle: Program = construct_cat_puzzle(CAT_MOD, self.cat_info.limitations_program_hash, inner_puzzle)
        return cat_puzzle

    def puzzle_hash_for_pk(self, pubkey: G1Element) -> bytes32:
        inner_puzzle_hash = create_revocation_layer(
            self.cat_info.hidden_puzzle_hash, self.standard_wallet.puzzle_hash_for_pk(pubkey)
        ).get_tree_hash()
        limitations_program_hash_hash = Program.to(self.cat_info.limitations_program_hash).get_tree_hash()
        return curry_and_treehash(
            QUOTED_CAT_MOD_HASH, CAT_MOD_HASH_HASH, limitations_program_hash_hash, inner_puzzle_hash
        )

    async def inner_puzzle_for_cat_puzhash(self, cat_hash: bytes32) -> Program:
        return create_revocation_layer(
            self.cat_info.hidden_puzzle_hash, (await super().inner_puzzle_for_cat_puzhash(cat_hash)).get_tree_hash()
        )

    @staticmethod
    def get_metadata_from_record(coin_record: WalletCoinRecord) -> RCATMetadata:
        metadata: MetadataTypes = coin_record.parsed_metadata()
        assert isinstance(metadata, RCATMetadata)
        return metadata

    async def make_inner_solution(
        self,
        coin: Coin,
        primaries: list[CreateCoin],
        conditions: tuple[Condition, ...] = tuple(),
    ) -> Program:
        record: Optional[
            DerivationRecord
        ] = await self.wallet_state_manager.puzzle_store.get_derivation_record_for_puzzle_hash(coin.puzzle_hash)
        if record is None:
            raise RuntimeError(f"Missing Derivation Record for CAT puzzle_hash {coin.puzzle_hash}")
        return solve_revocation_layer(
            self.standard_wallet.puzzle_for_pk(record.pubkey),
            (await super().make_inner_solution(coin, primaries=primaries, conditions=conditions)),
        )

    async def match_puzzle_info(self, puzzle_driver: PuzzleInfo) -> bool:
        if (
            AssetType(puzzle_driver.type()) == AssetType.CAT
            and puzzle_driver["tail"] == self.cat_info.limitations_program_hash
        ):
            inner_puzzle_driver: Optional[PuzzleInfo] = puzzle_driver.also()
            if inner_puzzle_driver is None:
                raise ValueError("Malformed puzzle driver passed to RCATWallet.match_puzzle_info")
            return (
                AssetType(inner_puzzle_driver.type()) == AssetType.REVOCATION_LAYER
                and bytes32(inner_puzzle_driver["hidden_puzzle_hash"]) == self.cat_info.hidden_puzzle_hash
            )
        return False

    async def get_puzzle_info(self, asset_id: bytes32) -> PuzzleInfo:
        return PuzzleInfo(
            {
                "type": AssetType.CAT.value,
                "tail": "0x" + self.cat_info.limitations_program_hash.hex(),
                "also": {
                    "type": AssetType.REVOCATION_LAYER.value,
                    "hidden_puzzle_hash": "0x" + self.cat_info.hidden_puzzle_hash.hex(),
                },
            }
        )

    async def match_hinted_coin(self, coin: Coin, hint: bytes32) -> bool:
        """
        This matches coins that are RCATs with the hint as the inner puzzle
        """

        hint_inner_hash: bytes32 = create_revocation_layer(
            self.cat_info.hidden_puzzle_hash,
            hint,
        ).get_tree_hash()
        if (
            construct_cat_puzzle(
                Program.to(CAT_MOD_HASH),
                self.cat_info.limitations_program_hash,
                hint_inner_hash,
                mod_code_hash=CAT_MOD_HASH_HASH,
            ).get_tree_hash_precalc(hint, CAT_MOD_HASH, CAT_MOD_HASH_HASH, hint_inner_hash)
            == coin.puzzle_hash
        ):
            return True
        return False


if TYPE_CHECKING:
    _dummy: WalletProtocol[CATCoinData] = RCATWallet()
