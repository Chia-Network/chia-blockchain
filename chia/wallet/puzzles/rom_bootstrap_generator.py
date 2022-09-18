from chia.types.blockchain_format.program import SerializedProgram

from .load_clvm import load_serialized_clvm

MOD = load_serialized_clvm("rom_bootstrap_generator.clvm")


def get_generator() -> SerializedProgram:
    return MOD
