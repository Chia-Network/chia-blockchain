from __future__ import annotations

import dataclasses
from typing import List, Optional

import pytest
from chia_rs import AugSchemeMPL, G1Element, G2Element, PrivateKey

from chia.rpc.wallet_rpc_client import WalletRpcClient
from chia.types.blockchain_format.coin import Coin as ConsensusCoin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.util.ints import uint64
from chia.util.streamable import Streamable, streamable
from chia.wallet.conditions import AggSigMe
from chia.wallet.derivation_record import DerivationRecord
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import (
    DEFAULT_HIDDEN_PUZZLE_HASH,
    calculate_synthetic_offset,
)
from chia.wallet.util.signer_protocol import (
    KeyHints,
    PathHint,
    SigningInstructions,
    SigningResponse,
    SigningTarget,
    Spend,
    SumHint,
    TransactionInfo,
    UnsignedTransaction,
    clvm_serialization_mode,
)
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_state_manager import WalletStateManager
from tests.wallet.conftest import WalletTestFramework


def test_signing_serialization() -> None:
    pubkey: G1Element = G1Element()
    message: bytes = b"message"

    coin: ConsensusCoin = ConsensusCoin(bytes32([0] * 32), bytes32([0] * 32), uint64(0))
    puzzle: Program = Program.to(1)
    solution: Program = Program.to([AggSigMe(pubkey, message).to_program()])

    coin_spend: CoinSpend = CoinSpend(coin, puzzle, solution)

    tx: UnsignedTransaction = UnsignedTransaction(
        TransactionInfo([Spend.from_coin_spend(coin_spend)]),
        SigningInstructions(
            KeyHints([], []),
            [SigningTarget(bytes(pubkey), message, bytes32([1] * 32))],
        ),
    )

    assert tx == UnsignedTransaction.from_program(Program.from_bytes(bytes(tx.as_program())))

    as_json_dict = {
        "coin": {
            "parent_coin_id": "0x" + tx.transaction_info.spends[0].coin.parent_coin_id.hex(),
            "puzzle_hash": "0x" + tx.transaction_info.spends[0].coin.puzzle_hash.hex(),
            "amount": tx.transaction_info.spends[0].coin.amount,
        },
        "puzzle": "0x" + bytes(tx.transaction_info.spends[0].puzzle).hex(),
        "solution": "0x" + bytes(tx.transaction_info.spends[0].solution).hex(),
    }
    assert tx.transaction_info.spends[0].to_json_dict() == as_json_dict

    # Test from_json_dict with the special case where it encounters the as_program serialization in the middle of JSON
    assert tx.transaction_info.spends[0] == Spend.from_json_dict(
        {
            "coin": bytes(tx.transaction_info.spends[0].coin.as_program()).hex(),
            "puzzle": bytes(tx.transaction_info.spends[0].puzzle).hex(),
            "solution": bytes(tx.transaction_info.spends[0].solution).hex(),
        }
    )

    # Test the optional serialization as blobs
    with clvm_serialization_mode(True):
        assert (
            tx.transaction_info.spends[0].to_json_dict()
            == bytes(tx.transaction_info.spends[0].as_program()).hex()  # type: ignore[comparison-overlap]
        )

    # Make sure it's still a dict if using a Streamable object
    @streamable
    @dataclasses.dataclass(frozen=True)
    class TempStreamable(Streamable):
        streamable_key: Spend

    with clvm_serialization_mode(True):
        assert TempStreamable(tx.transaction_info.spends[0]).to_json_dict() == {
            "streamable_key": bytes(tx.transaction_info.spends[0].as_program()).hex()
        }

    with clvm_serialization_mode(False):
        assert TempStreamable(tx.transaction_info.spends[0]).to_json_dict() == {"streamable_key": as_json_dict}

    with clvm_serialization_mode(False):
        assert TempStreamable(tx.transaction_info.spends[0]).to_json_dict() == {"streamable_key": as_json_dict}
        with clvm_serialization_mode(True):
            assert TempStreamable(tx.transaction_info.spends[0]).to_json_dict() == {
                "streamable_key": bytes(tx.transaction_info.spends[0].as_program()).hex()
            }
            with clvm_serialization_mode(False):
                assert TempStreamable(tx.transaction_info.spends[0]).to_json_dict() == {"streamable_key": as_json_dict}

    streamable_blob = bytes(tx.transaction_info.spends[0])
    with clvm_serialization_mode(True):
        clvm_streamable_blob = bytes(tx.transaction_info.spends[0])

    assert streamable_blob != clvm_streamable_blob
    Spend.from_bytes(streamable_blob)
    Spend.from_bytes(clvm_streamable_blob)
    assert Spend.from_bytes(streamable_blob) == Spend.from_bytes(clvm_streamable_blob) == tx.transaction_info.spends[0]

    with clvm_serialization_mode(False):
        assert bytes(tx.transaction_info.spends[0]) == streamable_blob

    inside_streamable_blob = bytes(TempStreamable(tx.transaction_info.spends[0]))
    with clvm_serialization_mode(True):
        inside_clvm_streamable_blob = bytes(TempStreamable(tx.transaction_info.spends[0]))

    assert inside_streamable_blob != inside_clvm_streamable_blob
    assert (
        TempStreamable.from_bytes(inside_streamable_blob)
        == TempStreamable.from_bytes(inside_clvm_streamable_blob)
        == TempStreamable(tx.transaction_info.spends[0])
    )


@pytest.mark.parametrize(
    "wallet_environments",
    [
        {
            "num_environments": 1,
            "blocks_needed": [1],
            "trusted": True,
            "reuse_puzhash": True,
        }
    ],
    indirect=True,
)
@pytest.mark.anyio
async def test_p2dohp_wallet_signer_protocol(wallet_environments: WalletTestFramework) -> None:
    wallet: Wallet = wallet_environments.environments[0].xch_wallet
    wallet_state_manager: WalletStateManager = wallet_environments.environments[0].wallet_state_manager
    wallet_rpc: WalletRpcClient = wallet_environments.environments[0].rpc_client

    # Test first that we can properly examine and sign a regular transaction
    puzzle: Program = await wallet.get_puzzle(new=False)
    puzzle_hash: bytes32 = puzzle.get_tree_hash()
    delegated_puzzle: Program = Program.to(None)
    delegated_puzzle_hash: bytes32 = delegated_puzzle.get_tree_hash()
    solution: Program = Program.to([None, None, None])

    coin: ConsensusCoin = ConsensusCoin(
        bytes32([0] * 32),
        puzzle_hash,
        uint64(0),
    )
    coin_spend: CoinSpend = CoinSpend(
        coin,
        puzzle,
        solution,
    )

    derivation_record: Optional[
        DerivationRecord
    ] = await wallet_state_manager.puzzle_store.get_derivation_record_for_puzzle_hash(puzzle_hash)
    assert derivation_record is not None
    pubkey: G1Element = derivation_record.pubkey
    synthetic_pubkey: G1Element = G1Element.from_bytes(puzzle.uncurry()[1].at("f").atom)
    message: bytes = delegated_puzzle_hash + coin.name() + wallet_state_manager.constants.AGG_SIG_ME_ADDITIONAL_DATA

    utx: UnsignedTransaction = UnsignedTransaction(
        TransactionInfo([Spend.from_coin_spend(coin_spend)]),
        (await wallet_rpc.gather_signing_info(spends=[Spend.from_coin_spend(coin_spend)])).signing_instructions,
    )
    assert utx.signing_instructions.key_hints.sum_hints == [
        SumHint(
            [pubkey.get_fingerprint().to_bytes(4, "big")],
            calculate_synthetic_offset(pubkey, DEFAULT_HIDDEN_PUZZLE_HASH).to_bytes(32, "big"),
        )
    ]
    assert utx.signing_instructions.key_hints.path_hints == [
        PathHint(
            wallet_state_manager.private_key.get_g1().get_fingerprint().to_bytes(4, "big"),
            [uint64(12381), uint64(8444), uint64(2), uint64(derivation_record.index)],
        )
    ]
    assert len(utx.signing_instructions.targets) == 1
    assert utx.signing_instructions.targets[0].pubkey == bytes(synthetic_pubkey)
    assert utx.signing_instructions.targets[0].message == message

    signing_responses: List[SigningResponse] = await wallet_state_manager.execute_signing_instructions(
        utx.signing_instructions
    )
    assert len(signing_responses) == 1
    assert signing_responses[0].hook == utx.signing_instructions.targets[0].hook
    assert AugSchemeMPL.verify(synthetic_pubkey, message, G2Element.from_bytes(signing_responses[0].signature))

    # Now test that we can partially sign a transaction
    ACS: Program = Program.to(1)
    ACS_PH: Program = Program.to(1).get_tree_hash()
    not_our_private_key: PrivateKey = PrivateKey.from_bytes(bytes(32))
    not_our_pubkey: G1Element = not_our_private_key.get_g1()
    not_our_message: bytes = b"not our message"
    not_our_coin: ConsensusCoin = ConsensusCoin(
        bytes32([0] * 32),
        ACS_PH,
        uint64(0),
    )
    not_our_coin_spend: CoinSpend = CoinSpend(not_our_coin, ACS, Program.to([[49, not_our_pubkey, not_our_message]]))

    not_our_utx: UnsignedTransaction = UnsignedTransaction(
        TransactionInfo([Spend.from_coin_spend(coin_spend), Spend.from_coin_spend(not_our_coin_spend)]),
        (
            await wallet_rpc.gather_signing_info(
                spends=[Spend.from_coin_spend(coin_spend), Spend.from_coin_spend(not_our_coin_spend)]
            )
        ).signing_instructions,
    )
    assert not_our_utx.signing_instructions.key_hints == utx.signing_instructions.key_hints
    assert len(not_our_utx.signing_instructions.targets) == 2
    assert not_our_utx.signing_instructions.targets[0].pubkey == bytes(synthetic_pubkey)
    assert not_our_utx.signing_instructions.targets[0].message == bytes(message)
    assert not_our_utx.signing_instructions.targets[1].pubkey == bytes(not_our_pubkey)
    assert not_our_utx.signing_instructions.targets[1].message == bytes(not_our_message)
    not_our_signing_instructions: SigningInstructions = not_our_utx.signing_instructions
    with pytest.raises(ValueError, match=r"not found \(or path/sum hinted to\)"):
        await wallet_state_manager.execute_signing_instructions(not_our_signing_instructions)
    with pytest.raises(ValueError, match=r"No pubkey found \(or path hinted to\) for fingerprint"):
        not_our_signing_instructions = dataclasses.replace(
            not_our_signing_instructions,
            key_hints=dataclasses.replace(
                not_our_signing_instructions.key_hints,
                sum_hints=[
                    *not_our_signing_instructions.key_hints.sum_hints,
                    SumHint([bytes(not_our_pubkey)], b""),
                ],
            ),
        )
        await wallet_state_manager.execute_signing_instructions(not_our_signing_instructions)
    with pytest.raises(ValueError, match="No root pubkey for fingerprint"):
        not_our_signing_instructions = dataclasses.replace(
            not_our_signing_instructions,
            key_hints=dataclasses.replace(
                not_our_signing_instructions.key_hints,
                path_hints=[
                    *not_our_signing_instructions.key_hints.path_hints,
                    PathHint(bytes(not_our_pubkey), [uint64(0)]),
                ],
            ),
        )
        await wallet_state_manager.execute_signing_instructions(not_our_signing_instructions)
    signing_responses_2 = await wallet_state_manager.execute_signing_instructions(
        not_our_signing_instructions, partial_allowed=True
    )
    assert len(signing_responses_2) == 1
    assert signing_responses_2 == signing_responses
