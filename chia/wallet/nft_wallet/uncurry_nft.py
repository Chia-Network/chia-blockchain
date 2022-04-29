from __future__ import annotations

from dataclasses import dataclass, field

from chia.types.blockchain_format.program import Program
from chia.wallet.puzzles.load_clvm import load_clvm

SINGLETON_TOP_LAYER_MOD = load_clvm("singleton_top_layer_v1_1.clvm")
NFT_MOD = load_clvm("nft_innerpuz.clvm")


@dataclass
class UncurriedNFT:
    """
    A simple solution for uncurry NFT puzzle.
    Initial the class with a full NFT puzzle, it will do a deep uncurry.
    This is the only place you need to change after modified the Chialisp curried parameters.
    """

    matched: bool = field(init=False)
    """If the puzzle is a NFT puzzle"""

    nft_mod_hash: Program = field(init=False)
    """NFT module hash"""

    singleton_struct: Program = field(init=False)
    """
    Singleton struct
    [singleton_mod_hash, singleton_launcher_id, launcher_puzhash]
    """
    singleton_mod_hash: Program = field(init=False)
    singleton_launcher_id: Program = field(init=False)
    launcher_puzhash: Program = field(init=False)

    owner_did: Program = field(init=False)
    """Owner's DID"""

    transfer_program_hash: Program = field(init=False)
    """Puzzle hash of the transfer program"""

    transfer_program_curry_params: Program = field(init=False)
    """
    Curried parameters of the transfer program
    [royalty_address, trade_price_percentage, settlement_mod_hash, cat_mod_hash]
    """
    royalty_address: Program = field(init=False)
    trade_price_percentage: Program = field(init=False)
    settlement_mod_hash: Program = field(init=False)
    cat_mod_hash: Program = field(init=False)

    metadata: Program = field(init=False)
    """
    NFT metadata
    [("u", data_uris), ("h", data_hash)]
    """
    data_uris: Program = field(init=False)
    data_hash: Program = field(init=False)

    @staticmethod
    def uncurry(puzzle: Program, raise_exception: bool = False) -> UncurriedNFT:
        """
        Try to uncurry a NFT puzzle
        :param puzzle: Puzzle
        :param raise_exception: If want to raise an exception when the puzzle is invalid
        :return Uncurried NFT
        """
        nft = UncurriedNFT()
        try:
            mod, curried_args = puzzle.uncurry()
            if mod == SINGLETON_TOP_LAYER_MOD:
                mod, curried_args = curried_args.rest().first().uncurry()
                if mod == NFT_MOD:
                    nft.matched = True
                    # Set nft parameters
                    (
                        nft.nft_mod_hash,
                        nft.singleton_struct,
                        nft.owner_did,
                        nft.transfer_program_hash,
                        nft.transfer_program_curry_params,
                        nft.metadata,
                    ) = curried_args.as_iter()
                    # Set singleton
                    nft.singleton_mod_hash = nft.singleton_struct.first()
                    nft.singleton_launcher_id = nft.singleton_struct.rest().first()
                    nft.launcher_puzhash = nft.singleton_struct.rest().rest()
                    # Set transfer program parameters
                    (
                        nft.royalty_address,
                        nft.trade_price_percentage,
                        nft.settlement_mod_hash,
                        nft.cat_mod_hash,
                    ) = nft.transfer_program_curry_params.as_iter()
                    # Set metadata
                    for kv_pair in nft.metadata.as_iter():
                        if kv_pair.first().as_atom() == b"u":
                            nft.data_uris = kv_pair.rest()
                        if kv_pair.first().as_atom() == b"h":
                            nft.data_hash = kv_pair.rest()
                    return nft
            nft.matched = False
            return nft
        except Exception:
            if raise_exception:
                raise ValueError(f"Cannot uncurry puzzle {puzzle}, it's not a NFT puzzle.")
            else:
                nft.matched = False
                return nft
