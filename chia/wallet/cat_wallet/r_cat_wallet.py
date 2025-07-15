from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import IntEnum
from typing import TYPE_CHECKING, Any, ClassVar, Optional, cast

from chia_rs import G1Element
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8, uint16
from typing_extensions import Self

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
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
    if TYPE_CHECKING:
        _protocol_check: ClassVar[WalletProtocol[CATCoinData]] = cast("RCATWallet", None)

    wallet_state_manager: WalletStateManager
    log: logging.Logger
    wallet_info: WalletInfo
    cat_info: RCATInfo
    standard_wallet: Wallet
    lineage_store: CATLineageStore
    wallet_type: ClassVar[WalletType] = WalletType.RCAT
    wallet_info_type: ClassVar[type[RCATInfo]] = RCATInfo

    # this is a legacy method and is not available on R-CAT wallets
    create_new_cat_wallet = None  # type: ignore[assignment]

    @staticmethod
    def default_wallet_name_for_unknown_cat(limitations_program_hash_hex: str) -> str:
        return f"Revocable-CAT {limitations_program_hash_hex[:16]}..."

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
        self.cat_info = cls.wallet_info_type(limitations_program_hash, None, hidden_puzzle_hash)
        info_as_string = bytes(self.cat_info).hex()
        self.wallet_info = await wallet_state_manager.user_store.create_wallet(name, cls.wallet_type, info_as_string)

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
        if rev_layer is None:
            raise ValueError("create_from_puzzle_info called on RCATWallet with a non R-CAT puzzle driver")
        return await cls.get_or_create_wallet_for_cat(
            wallet_state_manager,
            wallet,
            puzzle_driver["tail"].hex(),
            bytes32(rev_layer["hidden_puzzle_hash"]),
            name,
        )

    @property
    def cost_of_single_tx(self) -> int:
        return 78000000  # Estimate measured in testing

    @classmethod
    async def convert_to_revocable(
        cls,
        cat_wallet: CATWallet,
        hidden_puzzle_hash: bytes32,
    ) -> bool:
        if not cat_wallet.lineage_store.is_empty():
            cat_wallet.log.error("Received a revocable CAT to a CAT wallet that already has CATs")
            return False
        replace_self = cls()
        replace_self.standard_wallet = cat_wallet.standard_wallet
        replace_self.log = logging.getLogger(cat_wallet.get_name())
        replace_self.log.info(f"Converting CAT wallet {cat_wallet.id()} to R-CAT wallet")
        replace_self.wallet_state_manager = cat_wallet.wallet_state_manager
        replace_self.lineage_store = cat_wallet.lineage_store
        replace_self.cat_info = cls.wallet_info_type(
            cat_wallet.cat_info.limitations_program_hash, None, hidden_puzzle_hash
        )
        await cat_wallet.wallet_state_manager.user_store.update_wallet(
            WalletInfo(
                cat_wallet.id(), cat_wallet.get_name(), uint8(cls.wallet_type.value), bytes(replace_self.cat_info).hex()
            )
        )
        updated_wallet_info = await cat_wallet.wallet_state_manager.user_store.get_wallet_by_id(cat_wallet.id())
        assert updated_wallet_info is not None
        replace_self.wallet_info = updated_wallet_info

        cat_wallet.wallet_state_manager.wallets[cat_wallet.id()] = replace_self
        await cat_wallet.wallet_state_manager.puzzle_store.delete_wallet(cat_wallet.id())
        result = await cat_wallet.wallet_state_manager.create_more_puzzle_hashes()
        await result.commit(cat_wallet.wallet_state_manager)
        return True

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
                "tail": "0x" + self.get_asset_id(),
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
