from chia.wallet.puzzles.load_clvm import load_serialized_clvm

GENERATOR_FOR_SINGLE_COIN_MOD = load_serialized_clvm("generator_for_single_coin.clvm", package_or_requirement=__name__)
