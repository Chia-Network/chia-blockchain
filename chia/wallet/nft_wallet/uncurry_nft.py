from chia.types.blockchain_format.program import Program
from chia.wallet.puzzles.load_clvm import load_clvm

SINGLETON_TOP_LAYER_MOD = load_clvm("singleton_top_layer_v1_1.clvm")
NFT_MOD = load_clvm("nft_innerpuz.clvm")


class UncurriedNFT:
    """
    Uncurry result returned by the uncurry functions
    """

    matched: bool
    """
    If the puzzle is a NFT puzzle
    """
    nft_mod_hash: Program
    """
    Curried parameters
    """
    singleton_struct: Program
    """
    Singleton struct
    [singleton_mod_hash, singleton_launcher_id, launcher_puzhash]
    """
    singleton_mod_hash: Program
    singleton_launcher_id: Program
    launcher_puzhash: Program

    owner_did: Program
    """
    DID of the owner
    """
    transfer_program_hash: Program
    """
    Puzzle hash of the transfer program
    """
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

    def __init__(self, puzzle: Program, raise_exception: bool = False):
        """
        Try to uncurry a NFT puzzle
        :param puzzle: Puzzle
        :param raise_exception: If want to raise an exception when the puzzle is invalid
        """
        try:
            mod, curried_args = puzzle.uncurry()
            if mod == SINGLETON_TOP_LAYER_MOD:
                mod, curried_args = curried_args.rest().first().uncurry()
                if mod == NFT_MOD:
                    self.matched = True
                    # Set nft parameters
                    (
                        self.nft_mod_hash,
                        self.singleton_struct,
                        self.owner_did,
                        self.transfer_program_hash,
                        self.transfer_program_curry_params,
                        self.metadata,
                    ) = curried_args.as_iter()
                    # Set singleton
                    self.singleton_mod_hash = self.singleton_struct.first()
                    self.singleton_launcher_id = self.singleton_struct.rest().first()
                    self.launcher_puzhash = self.singleton_struct.rest().rest()
                    # Set transfer program parameters
                    (
                        self.royalty_address,
                        self.trade_price_percentage,
                        self.settlement_mod_hash,
                        self.cat_mod_hash,
                    ) = self.transfer_program_curry_params.as_iter()
                    # Set metadata
                    for kv_pair in self.metadata.as_iter():
                        if kv_pair.first().as_atom() == b"u":
                            self.data_uris = kv_pair.rest()
                        if kv_pair.first().as_atom() == b"h":
                            self.data_hash = kv_pair.rest()
                    return
            self.matched = False
        except Exception:
            if raise_exception:
                raise ValueError(f"Cannot uncurry puzzle {puzzle}, it's not a NFT puzzle.")
            else:
                self.matched = False
                import traceback

                print(f"exception: {traceback.format_exc()}")
