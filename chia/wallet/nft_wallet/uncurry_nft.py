from __future__ import annotations

from dataclasses import dataclass
from typing import Type, TypeVar

from chia.types.blockchain_format.program import Program
from chia.wallet.puzzles.load_clvm import load_clvm

SINGLETON_TOP_LAYER_MOD = load_clvm("singleton_top_layer_v1_1.clvm")
NFT_MOD = load_clvm("nft_innerpuz.clvm")


_T_UncurriedNFT = TypeVar("_T_UncurriedNFT", bound="UncurriedNFT")


@dataclass
class UncurriedNFT:
    """
    A simple solution for uncurry NFT puzzle.
    Initial the class with a full NFT puzzle, it will do a deep uncurry.
    This is the only place you need to change after modified the Chialisp curried parameters.
    """

    nft_mod_hash: Program
    """NFT module hash"""

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

    @classmethod
    def uncurry(cls: Type[_T_UncurriedNFT], puzzle: Program) -> _T_UncurriedNFT:
        """Try to uncurry a NFT puzzle

        :param puzzle: Puzzle
        :param raise_exception: If want to raise an exception when the puzzle is invalid
        :return Uncurried NFT
        """
        mod, curried_args = puzzle.uncurry()
        if mod != SINGLETON_TOP_LAYER_MOD:
            # TODO: proper message
            raise ValueError(f"Cannot uncurry puzzle, mod not a single top layer: {puzzle}")

        mod, curried_args = curried_args.rest().first().uncurry()
        if mod != NFT_MOD:
            # TODO: proper message
            raise ValueError(f"Cannot uncurry puzzle, mod not an NFT mode: {puzzle}")

        # nft parameters
        # TODO: Centralize the definition of this order with a class and construct
        #       an instance of it instead of using free variables.
        try:
            (
                nft_mod_hash,
                singleton_struct,
                owner_did,
                transfer_program_hash,
                transfer_program_curry_params,
                metadata,
            ) = curried_args.as_iter()
        except ValueError as e:
            # TODO: proper message
            raise ValueError(f"Cannot uncurry puzzle, incorrect number of arguemnts: {puzzle}") from e

        # singleton
        singleton_mod_hash = singleton_struct.first()
        singleton_launcher_id = singleton_struct.rest().first()
        launcher_puzhash = singleton_struct.rest().rest()

        # transfer program parameters
        try:
            (
                royalty_address,
                trade_price_percentage,
                settlement_mod_hash,
                cat_mod_hash,
            ) = transfer_program_curry_params.as_iter()
        except ValueError as e:
            # TODO: proper message
            raise ValueError(
                f"Cannot uncurry puzzle, incorrect number of transfer program curry parameters: {puzzle}",
            ) from e

        # metadata
        for kv_pair in metadata.as_iter():
            if kv_pair.first().as_atom() == b"u":
                data_uris = kv_pair.rest()
            if kv_pair.first().as_atom() == b"h":
                data_hash = kv_pair.rest()

        # TODO: How should we handle the case that no data_uris or no data_hash
        #       is found?  Is it ok if we find them multiple times and just
        #       ignore the first ones?

        return cls(
            nft_mod_hash=nft_mod_hash,
            singleton_struct=singleton_struct,
            singleton_mod_hash=singleton_mod_hash,
            singleton_launcher_id=singleton_launcher_id,
            launcher_puzhash=launcher_puzhash,
            owner_did=owner_did,
            transfer_program_hash=transfer_program_hash,
            transfer_program_curry_params=transfer_program_curry_params,
            royalty_address=royalty_address,
            trade_price_percentage=trade_price_percentage,
            settlement_mod_hash=settlement_mod_hash,
            cat_mod_hash=cat_mod_hash,
            metadata=metadata,
            data_uris=data_uris,
            data_hash=data_hash,
        )
