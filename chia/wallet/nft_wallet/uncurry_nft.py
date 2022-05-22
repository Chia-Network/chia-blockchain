from __future__ import annotations

from dataclasses import dataclass
from typing import Type, TypeVar

from chia.types.blockchain_format.program import Program
from chia.wallet.puzzles.load_clvm import load_clvm

SINGLETON_TOP_LAYER_MOD = load_clvm("singleton_top_layer_v1_1.clvm")
NFT_MOD = load_clvm("nft_state_layer.clvm")

_T_UncurriedNFT = TypeVar("_T_UncurriedNFT", bound="UncurriedNFT")


@dataclass(frozen=True)
class UncurriedNFT:
    """
    A simple solution for uncurry NFT puzzle.
    Initial the class with a full NFT puzzle, it will do a deep uncurry.
    This is the only place you need to change after modified the Chialisp curried parameters.
    """

    nft_mod_hash: Program
    """NFT module hash"""

    nft_state_layer: Program
    """NFT state layer puzzle"""

    singleton_struct: Program
    """
    Singleton struct
    [singleton_mod_hash, singleton_launcher_id, launcher_puzhash]
    """
    singleton_mod_hash: Program
    singleton_launcher_id: Program
    launcher_puzhash: Program

    owner_did: Program
    """Owner's DID"""

    metdata_updater_hash: Program
    """Metadata updater puzzle hash"""

    transfer_program_hash: Program
    """Puzzle hash of the transfer program"""

    transfer_program_curry_params: Program
    """
    Curried parameters of the transfer program
    [royalty_address, trade_price_percentage, settlement_mod_hash, cat_mod_hash]
    """
    royalty_address: Program
    trade_price_percentage: Program
    settlement_mod_hash: Program
    cat_mod_hash: Program

    metadata: Program
    """
    NFT metadata
    [("u", data_uris), ("h", data_hash)]
    """
    data_uris: Program
    data_hash: Program
    inner_puzzle: Program
    """NFT state layer inner puzzle"""

    @classmethod
    def uncurry(cls: Type[_T_UncurriedNFT], puzzle: Program) -> UncurriedNFT:
        """
        Try to uncurry a NFT puzzle
        :param cls UncurriedNFT class
        :param puzzle: Puzzle program
        :return Uncurried NFT
        """
        mod, curried_args = puzzle.uncurry()
        if mod != SINGLETON_TOP_LAYER_MOD:
            raise ValueError(f"Cannot uncurry NFT puzzle, failed on singleton top layer: Mod {mod}")
        try:
            (singleton_struct, nft_state_layer) = curried_args.as_iter()
            singleton_mod_hash = singleton_struct.first()
            singleton_launcher_id = singleton_struct.rest().first()
            launcher_puzhash = singleton_struct.rest().rest()
        except ValueError as e:
            raise ValueError(f"Cannot uncurry singleton top layer: Args {curried_args}") from e

        mod, curried_args = curried_args.rest().first().uncurry()
        if mod != NFT_MOD:
            raise ValueError(f"Cannot uncurry NFT puzzle, failed on NFT state layer: Mod {mod}")
        try:
            # Set nft parameters
            (nft_mod_hash, metadata, metdata_updater_hash, inner_puzzle) = curried_args.as_iter()

            # Set metadata
            for kv_pair in metadata.as_iter():
                if kv_pair.first().as_atom() == b"u":
                    data_uris = kv_pair.rest()
                if kv_pair.first().as_atom() == b"h":
                    data_hash = kv_pair.rest()

        except Exception as e:
            raise ValueError(f"Cannot uncurry NFT state layer: Args {curried_args}") from e
        return cls(
            nft_mod_hash=nft_mod_hash,
            nft_state_layer=nft_state_layer,
            singleton_struct=singleton_struct,
            singleton_mod_hash=singleton_mod_hash,
            singleton_launcher_id=singleton_launcher_id,
            launcher_puzhash=launcher_puzhash,
            metadata=metadata,
            data_uris=data_uris,
            data_hash=data_hash,
            metdata_updater_hash=metdata_updater_hash,
            inner_puzzle=inner_puzzle,
            # TODO Set/Remove following fields after NFT1 implemented
            owner_did=Program.to([]),
            transfer_program_hash=Program.to([]),
            transfer_program_curry_params=Program.to([]),
            royalty_address=Program.to([]),
            trade_price_percentage=Program.to([]),
            settlement_mod_hash=Program.to([]),
            cat_mod_hash=Program.to([]),
        )
