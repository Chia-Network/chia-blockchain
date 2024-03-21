from __future__ import annotations

import asyncio
import dataclasses
import threading
import time
from typing import List, Optional

import pytest
from chia_rs import AugSchemeMPL, G1Element, G2Element, PrivateKey

from chia._tests.environments.wallet import WalletStateTransition, WalletTestFramework
from chia.rpc.wallet_request_types import ApplySignatures, GatherSigningInfo, SubmitTransactions
from chia.rpc.wallet_rpc_client import WalletRpcClient
from chia.types.blockchain_format.coin import Coin as ConsensusCoin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend, make_spend
from chia.types.spend_bundle import SpendBundle
from chia.util.hash import std_hash
from chia.util.ints import uint64
from chia.util.streamable import ConversionError, Streamable, streamable
from chia.wallet.conditions import AggSigMe
from chia.wallet.derivation_record import DerivationRecord
from chia.wallet.derive_keys import _derive_path_unhardened
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import (
    DEFAULT_HIDDEN_PUZZLE_HASH,
    calculate_synthetic_offset,
)
from chia.wallet.signer_protocol import (
    KeyHints,
    PathHint,
    SignedTransaction,
    SigningInstructions,
    SigningResponse,
    SigningTarget,
    Spend,
    SumHint,
    TransactionInfo,
    UnsignedTransaction,
)
from chia.wallet.util.clvm_streamable import ClvmSerializationConfig, _ClvmSerializationMode, clvm_serialization_mode
from chia.wallet.util.tx_config import DEFAULT_COIN_SELECTION_CONFIG
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_state_manager import WalletStateManager


def test_signing_serialization() -> None:
    pubkey: G1Element = G1Element()
    message: bytes = b"message"

    coin: ConsensusCoin = ConsensusCoin(bytes32([0] * 32), bytes32([0] * 32), uint64(0))
    puzzle: Program = Program.to(1)
    solution: Program = Program.to([AggSigMe(pubkey, message).to_program()])

    coin_spend: CoinSpend = make_spend(coin, puzzle, solution)
    assert Spend.from_coin_spend(coin_spend).as_coin_spend() == coin_spend

    tx: UnsignedTransaction = UnsignedTransaction(
        TransactionInfo([Spend.from_coin_spend(coin_spend)]),
        SigningInstructions(
            KeyHints([], []),
            [SigningTarget(pubkey.get_fingerprint().to_bytes(4, "big"), message, bytes32([1] * 32))],
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

    # Test some json loading errors

    with pytest.raises(ConversionError):
        Spend.from_json_dict("blah")
    with pytest.raises(ConversionError):
        UnsignedTransaction.from_json_dict(streamable_blob.hex())


def test_serialization_config_thread_safe() -> None:
    def get_and_check_config(use: bool, wait_before: int, wait_after: int) -> None:
        with clvm_serialization_mode(use):
            time.sleep(wait_before)
            assert _ClvmSerializationMode.get_config() == ClvmSerializationConfig(use)
            time.sleep(wait_after)
        assert _ClvmSerializationMode.get_config() == ClvmSerializationConfig()

    thread_1 = threading.Thread(target=get_and_check_config, args=(True, 0, 2))
    thread_2 = threading.Thread(target=get_and_check_config, args=(False, 1, 3))
    thread_3 = threading.Thread(target=get_and_check_config, args=(True, 2, 4))
    thread_4 = threading.Thread(target=get_and_check_config, args=(False, 3, 5))

    thread_1.start()
    thread_2.start()
    thread_3.start()
    thread_4.start()

    thread_1.join()
    thread_2.join()
    thread_3.join()
    thread_4.join()


@pytest.mark.anyio
async def test_serialization_config_coroutine_safe() -> None:
    async def get_and_check_config(use: bool, wait_before: int, wait_after: int) -> None:
        with clvm_serialization_mode(use):
            await asyncio.sleep(wait_before)
            assert _ClvmSerializationMode.get_config() == ClvmSerializationConfig(use)
            await asyncio.sleep(wait_after)
        assert _ClvmSerializationMode.get_config() == ClvmSerializationConfig()

    await get_and_check_config(True, 0, 2)
    await get_and_check_config(False, 1, 3)
    await get_and_check_config(True, 2, 4)
    await get_and_check_config(False, 3, 5)


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
    [coin] = await wallet.select_coins(uint64(0), DEFAULT_COIN_SELECTION_CONFIG)
    puzzle: Program = await wallet.puzzle_for_puzzle_hash(coin.puzzle_hash)
    delegated_puzzle: Program = Program.to(None)
    delegated_puzzle_hash: bytes32 = delegated_puzzle.get_tree_hash()
    solution: Program = Program.to([None, None, None])

    coin_spend: CoinSpend = make_spend(
        coin,
        puzzle,
        solution,
    )

    derivation_record: Optional[DerivationRecord] = (
        await wallet_state_manager.puzzle_store.get_derivation_record_for_puzzle_hash(coin.puzzle_hash)
    )
    assert derivation_record is not None
    pubkey: G1Element = derivation_record.pubkey
    synthetic_pubkey: G1Element = G1Element.from_bytes(puzzle.uncurry()[1].at("f").atom)
    message: bytes = delegated_puzzle_hash + coin.name() + wallet_state_manager.constants.AGG_SIG_ME_ADDITIONAL_DATA

    utx: UnsignedTransaction = UnsignedTransaction(
        TransactionInfo([Spend.from_coin_spend(coin_spend)]),
        (
            await wallet_rpc.gather_signing_info(GatherSigningInfo(spends=[Spend.from_coin_spend(coin_spend)]))
        ).signing_instructions,
    )
    assert utx.signing_instructions.key_hints.sum_hints == [
        SumHint(
            [pubkey.get_fingerprint().to_bytes(4, "big")],
            calculate_synthetic_offset(pubkey, DEFAULT_HIDDEN_PUZZLE_HASH).to_bytes(32, "big"),
            wallet_state_manager.main_wallet.puzzle_for_pk(pubkey).uncurry()[1].at("f").as_atom(),
        )
    ]
    assert utx.signing_instructions.key_hints.path_hints == [
        PathHint(
            wallet_state_manager.root_pubkey.get_fingerprint().to_bytes(4, "big"),
            [uint64(12381), uint64(8444), uint64(2), uint64(derivation_record.index)],
        )
    ]
    assert len(utx.signing_instructions.targets) == 1
    assert utx.signing_instructions.targets[0].fingerprint == synthetic_pubkey.get_fingerprint().to_bytes(4, "big")
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
    not_our_private_key: PrivateKey = PrivateKey.from_bytes(bytes([1] * 32))
    not_our_pubkey: G1Element = not_our_private_key.get_g1()
    not_our_message: bytes = b"not our message"
    not_our_coin: ConsensusCoin = ConsensusCoin(
        bytes32([0] * 32),
        ACS_PH,
        uint64(0),
    )
    not_our_coin_spend: CoinSpend = make_spend(not_our_coin, ACS, Program.to([[49, not_our_pubkey, not_our_message]]))

    not_our_utx: UnsignedTransaction = UnsignedTransaction(
        TransactionInfo([Spend.from_coin_spend(coin_spend), Spend.from_coin_spend(not_our_coin_spend)]),
        (
            await wallet_rpc.gather_signing_info(
                GatherSigningInfo(spends=[Spend.from_coin_spend(coin_spend), Spend.from_coin_spend(not_our_coin_spend)])
            )
        ).signing_instructions,
    )
    assert not_our_utx.signing_instructions.key_hints == utx.signing_instructions.key_hints
    assert len(not_our_utx.signing_instructions.targets) == 2
    assert not_our_utx.signing_instructions.targets[0].fingerprint == synthetic_pubkey.get_fingerprint().to_bytes(
        4, "big"
    )
    assert not_our_utx.signing_instructions.targets[0].message == bytes(message)
    assert not_our_utx.signing_instructions.targets[1].fingerprint == not_our_pubkey.get_fingerprint().to_bytes(
        4, "big"
    )
    assert not_our_utx.signing_instructions.targets[1].message == bytes(not_our_message)
    not_our_signing_instructions: SigningInstructions = not_our_utx.signing_instructions
    with pytest.raises(ValueError, match=r"not found \(or path/sum hinted to\)"):
        await wallet_state_manager.execute_signing_instructions(not_our_signing_instructions)
    with pytest.raises(ValueError, match=r"No pubkey found \(or path hinted to\) for fingerprint"):
        await wallet_state_manager.execute_signing_instructions(
            dataclasses.replace(
                not_our_signing_instructions,
                key_hints=dataclasses.replace(
                    not_our_signing_instructions.key_hints,
                    sum_hints=[
                        *not_our_signing_instructions.key_hints.sum_hints,
                        SumHint([bytes(not_our_pubkey)], std_hash(b"sum hint only"), bytes(G1Element())),
                    ],
                ),
            )
        )
    with pytest.raises(ValueError, match="No root pubkey for fingerprint"):
        await wallet_state_manager.execute_signing_instructions(
            dataclasses.replace(
                not_our_signing_instructions,
                key_hints=dataclasses.replace(
                    not_our_signing_instructions.key_hints,
                    path_hints=[
                        *not_our_signing_instructions.key_hints.path_hints,
                        PathHint(bytes(not_our_pubkey), [uint64(0)]),
                    ],
                ),
            )
        )
    signing_responses_2 = await wallet_state_manager.execute_signing_instructions(
        not_our_signing_instructions, partial_allowed=True
    )
    assert len(signing_responses_2) == 2
    assert (
        bytes(AugSchemeMPL.aggregate([G2Element.from_bytes(sig.signature) for sig in signing_responses_2]))
        == signing_responses[0].signature
    )

    signed_txs: List[SignedTransaction] = (
        await wallet_rpc.apply_signatures(
            ApplySignatures(spends=[Spend.from_coin_spend(coin_spend)], signing_responses=signing_responses)
        )
    ).signed_transactions
    await wallet_rpc.submit_transactions(SubmitTransactions(signed_transactions=signed_txs))
    await wallet_environments.full_node.wait_bundle_ids_in_mempool(
        [
            SpendBundle(
                [spend.as_coin_spend() for tx in signed_txs for spend in tx.transaction_info.spends],
                G2Element.from_bytes(signing_responses[0].signature),
            ).name()
        ]
    )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                # We haven't submitted a TransactionRecord so the wallet won't know about this until confirmed
                pre_block_balance_updates={},
                post_block_balance_updates={
                    1: {
                        "confirmed_wallet_balance": -1 * coin.amount,
                        "unconfirmed_wallet_balance": -1 * coin.amount,
                        "spendable_balance": -1 * coin.amount,
                        "max_send_amount": -1 * coin.amount,
                        "unspent_coin_count": -1,
                    },
                },
            ),
        ]
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
async def test_p2blsdohp_execute_signing_instructions(wallet_environments: WalletTestFramework) -> None:
    wallet: Wallet = wallet_environments.environments[0].xch_wallet
    root_sk: PrivateKey = wallet.wallet_state_manager.get_master_private_key()
    root_pk: G1Element = root_sk.get_g1()
    root_fingerprint: bytes = root_pk.get_fingerprint().to_bytes(4, "big")

    # Test just a path hint
    test_name: bytes32 = std_hash(b"path hint only")
    child_sk: PrivateKey = _derive_path_unhardened(root_sk, [uint64(1), uint64(2), uint64(3), uint64(4)])
    signing_responses: List[SigningResponse] = await wallet.execute_signing_instructions(
        SigningInstructions(
            KeyHints(
                [],
                [PathHint(root_fingerprint, [uint64(1), uint64(2), uint64(3), uint64(4)])],
            ),
            [SigningTarget(child_sk.get_g1().get_fingerprint().to_bytes(4, "big"), test_name, test_name)],
        )
    )
    assert signing_responses == [SigningResponse(bytes(AugSchemeMPL.sign(child_sk, test_name)), test_name)]

    # Test just a sum hint
    test_name = std_hash(b"sum hint only")
    other_sk: PrivateKey = PrivateKey.from_bytes(test_name)
    sum_pk: G1Element = other_sk.get_g1() + root_pk
    signing_instructions: SigningInstructions = SigningInstructions(
        KeyHints(
            [SumHint([root_fingerprint], test_name, bytes(sum_pk))],
            [],
        ),
        [SigningTarget(sum_pk.get_fingerprint().to_bytes(4, "big"), test_name, test_name)],
    )
    for partial_allowed in (True, False):
        signing_responses = await wallet.execute_signing_instructions(signing_instructions, partial_allowed)
        assert signing_responses == [
            SigningResponse(
                bytes(
                    AugSchemeMPL.aggregate(
                        [
                            AugSchemeMPL.sign(other_sk, test_name, sum_pk),
                            AugSchemeMPL.sign(root_sk, test_name, sum_pk),
                        ]
                    )
                ),
                test_name,
            ),
        ]
    # Toss in a random SigningTarget to see that the responses split up
    signing_instructions = dataclasses.replace(
        signing_instructions,
        targets=[
            SigningTarget(sum_pk.get_fingerprint().to_bytes(4, "big"), test_name, test_name),
            SigningTarget(b"random fingerprint", test_name, test_name),
        ],
    )
    signing_responses = await wallet.execute_signing_instructions(signing_instructions, partial_allowed=True)
    assert signing_responses == [
        SigningResponse(
            bytes(
                AugSchemeMPL.sign(root_sk, test_name, sum_pk),
            ),
            test_name,
        ),
        SigningResponse(
            bytes(
                AugSchemeMPL.sign(other_sk, test_name, sum_pk),
            ),
            test_name,
        ),
    ]

    # Test both path and sum hint
    test_name = std_hash(b"path and sum hint")
    child_sk = _derive_path_unhardened(root_sk, [uint64(1), uint64(2), uint64(3), uint64(4)])
    other_sk = PrivateKey.from_bytes(test_name)
    sum_pk = child_sk.get_g1() + other_sk.get_g1()
    signing_instructions = SigningInstructions(
        KeyHints(
            [SumHint([child_sk.get_g1().get_fingerprint().to_bytes(4, "big")], test_name, bytes(sum_pk))],
            [PathHint(root_fingerprint, [uint64(1), uint64(2), uint64(3), uint64(4)])],
        ),
        [SigningTarget(sum_pk.get_fingerprint().to_bytes(4, "big"), test_name, test_name)],
    )
    for partial_allowed in (True, False):
        signing_responses = await wallet.execute_signing_instructions(signing_instructions, partial_allowed)
        assert signing_responses == [
            SigningResponse(
                bytes(
                    AugSchemeMPL.aggregate(
                        [
                            AugSchemeMPL.sign(other_sk, test_name, sum_pk),
                            AugSchemeMPL.sign(child_sk, test_name, sum_pk),
                        ]
                    )
                ),
                test_name,
            ),
        ]

    # Test partial signing
    test_name = std_hash(b"path and sum hint partial")
    test_name_2 = std_hash(test_name)
    root_sk_2 = PrivateKey.from_bytes(std_hash(b"a key we do not have"))
    child_sk = _derive_path_unhardened(root_sk, [uint64(1), uint64(2), uint64(3), uint64(4)])
    child_sk_2 = _derive_path_unhardened(root_sk_2, [uint64(1), uint64(2), uint64(3), uint64(4)])
    other_sk = PrivateKey.from_bytes(test_name)
    other_sk_2 = PrivateKey.from_bytes(test_name_2)
    sum_pk = child_sk.get_g1() + other_sk.get_g1()
    sum_pk_2 = child_sk_2.get_g1() + other_sk_2.get_g1()
    signing_responses = await wallet.execute_signing_instructions(
        SigningInstructions(
            KeyHints(
                [
                    SumHint([child_sk.get_g1().get_fingerprint().to_bytes(4, "big")], test_name, bytes(sum_pk)),
                    SumHint([child_sk_2.get_g1().get_fingerprint().to_bytes(4, "big")], test_name_2, bytes(sum_pk_2)),
                ],
                [
                    PathHint(root_fingerprint, [uint64(1), uint64(2), uint64(3), uint64(4)]),
                    PathHint(
                        root_sk_2.get_g1().get_fingerprint().to_bytes(4, "big"),
                        [uint64(1), uint64(2), uint64(3), uint64(4)],
                    ),
                ],
            ),
            [
                SigningTarget(sum_pk.get_fingerprint().to_bytes(4, "big"), test_name, test_name),
                SigningTarget(sum_pk_2.get_fingerprint().to_bytes(4, "big"), test_name_2, test_name_2),
            ],
        ),
        partial_allowed=True,
    )
    assert signing_responses == [
        SigningResponse(
            bytes(
                AugSchemeMPL.sign(child_sk, test_name, sum_pk),
            ),
            test_name,
        ),
        SigningResponse(
            bytes(AugSchemeMPL.sign(other_sk, test_name, sum_pk)),
            test_name,
        ),
        SigningResponse(bytes(AugSchemeMPL.sign(other_sk_2, test_name_2, sum_pk_2)), test_name_2),
    ]

    # Test errors
    unknown_path_hint = SigningInstructions(
        KeyHints(
            [],
            [PathHint(b"unknown fingerprint", [uint64(1), uint64(2), uint64(3), uint64(4)])],
        ),
        [],
    )
    unknown_sum_hint = SigningInstructions(
        KeyHints(
            [SumHint([b"unknown fingerprint"], b"", bytes(G1Element()))],
            [],
        ),
        [],
    )
    unknown_target = SigningInstructions(
        KeyHints(
            [],
            [],
        ),
        [SigningTarget(b"unknown fingerprint", b"", std_hash(b"some hook"))],
    )
    with pytest.raises(ValueError, match="No root pubkey for fingerprint"):
        await wallet.execute_signing_instructions(unknown_path_hint)
    with pytest.raises(ValueError, match="No pubkey found"):
        await wallet.execute_signing_instructions(unknown_sum_hint)
    with pytest.raises(ValueError, match="not found"):
        await wallet.execute_signing_instructions(unknown_target)

    # Test no private key partial sign sum hint
    wallet.wallet_state_manager.private_key = None
    test_name = std_hash(b"sum hint partial no private key")
    other_sk = PrivateKey.from_bytes(test_name)
    sum_pk = other_sk.get_g1() + root_pk
    signing_responses = await wallet.execute_signing_instructions(
        SigningInstructions(
            KeyHints(
                [SumHint([root_fingerprint], test_name, bytes(sum_pk))],
                [],
            ),
            [SigningTarget(sum_pk.get_fingerprint().to_bytes(4, "big"), test_name, test_name)],
        ),
        partial_allowed=True,
    )
    assert signing_responses == [SigningResponse(bytes(AugSchemeMPL.sign(other_sk, test_name, sum_pk)), test_name)]
