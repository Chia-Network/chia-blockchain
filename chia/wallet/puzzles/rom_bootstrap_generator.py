from chia.types.blockchain_format.program import SerializedProgram

from .load_clvm import load_clvm

MOD = SerializedProgram.from_bytes(load_clvm("rom_bootstrap_generator.clvm").as_bin())


def get_generator():
    return MOD
