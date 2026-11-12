from __future__ import annotations

import pytest
from chia_rs import Coin
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint64

from chia.types.blockchain_format.program import Program
from chia.types.coin_spend import make_spend
from chia.wallet.cat_wallet.cat_utils import CATPuzzle
from chia.wallet.conditions import Remark
from chia.wallet.puzzles.puzzle_drivers import ACSPuzzle, ACSSolution, UnknownPuzzle, UnknownSolution
from chia.wallet.uncurried_puzzle import uncurry_puzzle
from chia.wallet.vc_wallet.cr_cat_drivers import (
    CRCAT,
    PENDING_VC_ANNOUNCEMENT,
    CRCATSpend,
    CredentialRestrictionLayer,
    CredentialRestrictionLayerSolution,
    PendingApprovalPuzzle,
    ProofsChecker,
)


def test_proofs_checker_and_pending_approval_match_failures() -> None:
    assert ProofsChecker.match(unknown_puzzle=UnknownPuzzle(known_program=ACSPuzzle().program)) is None

    assert PendingApprovalPuzzle.match(unknown_puzzle=UnknownPuzzle(known_program=ACSPuzzle().program)) is None

    # Wrong ACS solution content inside PENDING_VC_ANNOUNCEMENT curry
    assert (
        PendingApprovalPuzzle.match(
            unknown_puzzle=UnknownPuzzle(known_program=PENDING_VC_ANNOUNCEMENT.curry(Program.to(1)))
        )
        is None
    )
    assert (
        PendingApprovalPuzzle.match(
            unknown_puzzle=UnknownPuzzle(
                known_program=PENDING_VC_ANNOUNCEMENT.curry(
                    ACSSolution(conditions=[Remark(rest=Program.to("x")), Remark(rest=Program.to("y"))]).program
                )
            )
        )
        is None
    )
    assert (
        PendingApprovalPuzzle.match(
            unknown_puzzle=UnknownPuzzle(
                known_program=PENDING_VC_ANNOUNCEMENT.curry(
                    ACSSolution(conditions=[Remark(rest=Program.to("not create coin"))]).program
                )
            )
        )
        is None
    )

    matched = PendingApprovalPuzzle.match(
        unknown_puzzle=UnknownPuzzle(
            known_program=PendingApprovalPuzzle(target_puzzle_hash=bytes32.zeros, amount=uint64(1)).program
        )
    )
    assert matched == PendingApprovalPuzzle(target_puzzle_hash=bytes32.zeros, amount=uint64(1))


def test_credential_restriction_match_failures() -> None:
    assert CredentialRestrictionLayerSolution.match(UnknownSolution(program=Program.to([1, 2, 3]))) is None

    # Valid CR layer shape but unknown proofs checker
    from chia.wallet.vc_wallet.cr_cat_drivers import CREDENTIAL_RESTRICTION, CREDENTIAL_STRUCT

    first_curry = CREDENTIAL_RESTRICTION.curry(CREDENTIAL_STRUCT, [bytes32.zeros], Program.to("bad checker"))
    bad_cr = first_curry.curry(first_curry.get_tree_hash(), ACSPuzzle().program)
    assert CredentialRestrictionLayer.match(unknown_puzzle=UnknownPuzzle(known_program=bad_cr)) is None


def test_crcat_is_cr_cat_and_spend_errors() -> None:
    assert CRCAT.is_cr_cat(uncurry_puzzle(ACSPuzzle().program)) == (False, "top most layer is not a CAT")

    cat_only = CATPuzzle(tail_hash=bytes32.zeros, inner_puzzle=ACSPuzzle())
    assert CRCAT.is_cr_cat(uncurry_puzzle(cat_only.program)) == (False, "CAT is not credential restricted")

    coin = Coin(bytes32.zeros, bytes32.zeros, uint64(1))
    non_cat_spend = make_spend(coin, ACSPuzzle().program, Program.to([]))
    with pytest.raises(ValueError, match="Spend did not contain a CAT puzzle"):
        CRCAT.get_current_from_coin_spend(non_cat_spend)
    with pytest.raises(ValueError, match="Spend was not a CRCAT spend"):
        CRCATSpend.from_coin_spend(non_cat_spend)

    cat_spend = make_spend(coin, cat_only.program, Program.to([Program.to([]), None, None, None, None]))
    with pytest.raises(ValueError, match="CAT puzzle did not contain a credential restriction layer"):
        CRCAT.get_current_from_coin_spend(cat_spend)
    with pytest.raises(ValueError, match="Spend was not a CRCAT spend"):
        CRCATSpend.from_coin_spend(cat_spend)

    proofs_checker = ProofsChecker(flags=["flag"])
    cr_layer = CredentialRestrictionLayer(
        authorized_providers=[bytes32.zeros], proofs_checker=proofs_checker, inner_puzzle=ACSPuzzle()
    )
    cr_cat = CATPuzzle(tail_hash=bytes32.zeros, inner_puzzle=cr_layer)
    # Valid CR-CAT puzzle but solution arity wrong for CredentialRestrictionLayerSolution
    bad_sol_spend = make_spend(
        coin,
        cr_cat.program,
        Program.to([Program.to([1, 2, 3]), None, None, None, None]),
    )
    with pytest.raises(ValueError, match="Spend was not a CRCAT spend"):
        CRCATSpend.from_coin_spend(bad_sol_spend)


@pytest.mark.anyio
async def test_crcat_wallet_unknown_proofs_checker() -> None:
    from unittest.mock import MagicMock

    from chia.wallet.outer_puzzles import AssetType
    from chia.wallet.puzzle_drivers import PuzzleInfo
    from chia.wallet.vc_wallet.cr_cat_wallet import CRCATWallet

    puzzle_info = PuzzleInfo(
        {
            "type": AssetType.CAT.value,
            "tail": "0x" + bytes32.zeros.hex(),
            "also": {
                "type": AssetType.CR.value,
                "authorized_providers": ["0x" + bytes32.zeros.hex()],
                "proofs_checker": Program.to([1]),
            },
        }
    )
    with pytest.raises(ValueError, match="Unknown proofs checker found in CR-CAT puzzle driver"):
        await CRCATWallet.create_from_puzzle_info(MagicMock(), MagicMock(), puzzle_info)
