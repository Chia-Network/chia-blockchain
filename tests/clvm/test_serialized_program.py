import pytest
from unittest import TestCase

from clvm import SExp
from src.types.program import SerializedProgram, Program
from src.wallet.puzzles.load_clvm import load_clvm


SHA256TREE_MOD = load_clvm("sha256tree_module.clvm")

# TODO: test multiple args

class TestSerializedProgram(TestCase):
    def test_tree_hash(self):

        p_result = SHA256TREE_MOD.run(SHA256TREE_MOD)
        sp = SerializedProgram.from_bytes(bytes(SHA256TREE_MOD))
        cost, sp_result = sp.run_with_cost(sp)
        self.assertEqual(p_result, sp_result)

    def test_serialization(self):
        s0 = SerializedProgram.from_bytes(b"\x00")
        p0 = Program.from_bytes(b"\x00")
        # TODO: enable when clvm updated for minimal encoding of zero
        # self.assertEqual(bytes(p0), bytes(s0))
