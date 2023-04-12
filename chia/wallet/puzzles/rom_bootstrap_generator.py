from __future__ import annotations

from chia.types.blockchain_format.serialized_program import SerializedProgram

from .load_clvm import load_serialized_clvm_maybe_recompile

MOD = load_serialized_clvm_maybe_recompile("rom_bootstrap_generator.clsp")


def get_generator() -> SerializedProgram:
    return MOD
