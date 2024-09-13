from __future__ import annotations

import dataclasses
from typing import List, Optional

import click
import pytest
from chia_rs import AugSchemeMPL, G1Element, G2Element, PrivateKey
from click.testing import CliRunner

from chia._tests.cmds.test_cmd_framework import check_click_parsing
from chia._tests.cmds.wallet.test_consts import STD_TX
from chia._tests.environments.wallet import WalletStateTransition, WalletTestFramework
from chia.cmds.cmd_classes import NeedsWalletRPC, WalletClientInfo, chia_command
from chia.cmds.cmds_util import TransactionBundle
from chia.cmds.signer import (
    ApplySignaturesCMD,
    ExecuteSigningInstructionsCMD,
    GatherSigningInfoCMD,
    PushTransactionsCMD,
    QrCodeDisplay,
    SPIn,
    SPOut,
    TransactionsIn,
    TransactionsOut,
)
from chia.rpc.util import ALL_TRANSLATION_LAYERS
from chia.rpc.wallet_request_types import (
    ApplySignatures,
    ExecuteSigningInstructions,
    GatherSigningInfo,
    GatherSigningInfoResponse,
    SubmitTransactions,
)
from chia.rpc.wallet_rpc_client import WalletRpcClient
from chia.types.blockchain_format.coin import Coin as ConsensusCoin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend, make_spend
from chia.util.hash import std_hash
from chia.util.ints import uint64
from chia.util.streamable import Streamable
from chia.wallet.conditions import AggSigMe
from chia.wallet.derivation_record import DerivationRecord
from chia.wallet.derive_keys import _derive_path_unhardened
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import (
    DEFAULT_HIDDEN_PUZZLE_HASH,
    calculate_synthetic_offset,
)
from chia.wallet.signer_protocol import (
    Coin,
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
from chia.wallet.util.blind_signer_tl import (
    BLIND_SIGNER_TRANSLATION,
    BSTLPathHint,
    BSTLSigningInstructions,
    BSTLSigningResponse,
    BSTLSigningTarget,
    BSTLSumHint,
    BSTLUnsignedTransaction,
)
from chia.wallet.util.clvm_streamable import (
    TranslationLayer,
    TranslationLayerMapping,
    byte_serialize_clvm_streamable,
    clvm_streamable,
    json_deserialize_with_clvm_streamable,
    json_serialize_with_clvm_streamable,
)
from chia.wallet.util.tx_config import DEFAULT_TX_CONFIG
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_spend_bundle import WalletSpendBundle
from chia.wallet.wallet_state_manager import WalletStateManager


def test_unsigned_transaction_type() -> None:
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

    assert tx == json_deserialize_with_clvm_streamable(json_serialize_with_clvm_streamable(tx), UnsignedTransaction)
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
    async with wallet.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=False) as action_scope:
        [coin] = await wallet.select_coins(uint64(0), action_scope)
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

    signing_responses: List[SigningResponse] = (
        await wallet_rpc.execute_signing_instructions(ExecuteSigningInstructions(utx.signing_instructions))
    ).signing_responses
    assert len(signing_responses) == 1
    assert signing_responses[0].hook == utx.signing_instructions.targets[0].hook
    assert AugSchemeMPL.verify(synthetic_pubkey, message, G2Element.from_bytes(signing_responses[0].signature))

    # Now test that we can partially sign a transaction
    ACS: Program = Program.to(1)
    ACS_PH = Program.to(1).get_tree_hash()
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
            WalletSpendBundle(
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

    # And test that we can get compressed versions if we want
    request = GatherSigningInfo(
        [Spend.from_coin_spend(coin_spend), Spend.from_coin_spend(not_our_coin_spend)]
    ).to_json_dict()
    response_dict = await wallet_rpc.fetch("gather_signing_info", {"translation": "chip-0029", **request})
    response: GatherSigningInfoResponse = json_deserialize_with_clvm_streamable(
        response_dict, GatherSigningInfoResponse, translation_layer=BLIND_SIGNER_TRANSLATION
    )
    assert response.signing_instructions == not_our_utx.signing_instructions


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


def test_blind_signer_translation_layer() -> None:
    sum_hints: List[SumHint] = [
        SumHint([b"a", b"b", b"c"], b"offset", b"final"),
        SumHint([b"c", b"b", b"a"], b"offset2", b"final"),
    ]
    path_hints: List[PathHint] = [
        PathHint(b"root1", [uint64(1), uint64(2), uint64(3)]),
        PathHint(b"root2", [uint64(4), uint64(5), uint64(6)]),
    ]
    signing_targets: List[SigningTarget] = [
        SigningTarget(b"pubkey", b"message", bytes32([0] * 32)),
        SigningTarget(b"pubkey2", b"message2", bytes32([1] * 32)),
    ]

    instructions: SigningInstructions = SigningInstructions(
        KeyHints(sum_hints, path_hints),
        signing_targets,
    )
    transaction: UnsignedTransaction = UnsignedTransaction(
        TransactionInfo([]),
        instructions,
    )
    signing_response: SigningResponse = SigningResponse(
        b"signature",
        bytes32([1] * 32),
    )

    bstl_sum_hints: List[BSTLSumHint] = [
        BSTLSumHint([b"a", b"b", b"c"], b"offset", b"final"),
        BSTLSumHint([b"c", b"b", b"a"], b"offset2", b"final"),
    ]
    bstl_path_hints: List[BSTLPathHint] = [
        BSTLPathHint(b"root1", [uint64(1), uint64(2), uint64(3)]),
        BSTLPathHint(b"root2", [uint64(4), uint64(5), uint64(6)]),
    ]
    bstl_signing_targets: List[BSTLSigningTarget] = [
        BSTLSigningTarget(b"pubkey", b"message", bytes32([0] * 32)),
        BSTLSigningTarget(b"pubkey2", b"message2", bytes32([1] * 32)),
    ]

    bstl_instructions: BSTLSigningInstructions = BSTLSigningInstructions(
        bstl_sum_hints,
        bstl_path_hints,
        bstl_signing_targets,
    )
    bstl_transaction: BSTLUnsignedTransaction = BSTLUnsignedTransaction(
        bstl_sum_hints,
        bstl_path_hints,
        bstl_signing_targets,
    )
    bstl_signing_response: BSTLSigningResponse = BSTLSigningResponse(
        b"signature",
        bytes32([1] * 32),
    )
    bstl_instructions_json = json_serialize_with_clvm_streamable(bstl_instructions)
    bstl_transaction_json = json_serialize_with_clvm_streamable(bstl_transaction)
    bstl_signing_response_json = json_serialize_with_clvm_streamable(bstl_signing_response)
    assert bstl_instructions_json == json_serialize_with_clvm_streamable(
        instructions, translation_layer=BLIND_SIGNER_TRANSLATION
    )
    assert bstl_transaction_json == json_serialize_with_clvm_streamable(
        transaction, translation_layer=BLIND_SIGNER_TRANSLATION
    )
    assert bstl_signing_response_json == json_serialize_with_clvm_streamable(
        signing_response, translation_layer=BLIND_SIGNER_TRANSLATION
    )

    assert (
        json_deserialize_with_clvm_streamable(
            bstl_instructions_json, SigningInstructions, translation_layer=BLIND_SIGNER_TRANSLATION
        )
        == instructions
    )
    assert (
        json_deserialize_with_clvm_streamable(
            bstl_transaction_json, UnsignedTransaction, translation_layer=BLIND_SIGNER_TRANSLATION
        )
        == transaction
    )
    assert (
        json_deserialize_with_clvm_streamable(
            bstl_signing_response_json, SigningResponse, translation_layer=BLIND_SIGNER_TRANSLATION
        )
        == signing_response
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
async def test_signer_commands(wallet_environments: WalletTestFramework) -> None:
    wallet: Wallet = wallet_environments.environments[0].xch_wallet
    wallet_state_manager: WalletStateManager = wallet_environments.environments[0].wallet_state_manager
    wallet_rpc: WalletRpcClient = wallet_environments.environments[0].rpc_client
    client_info: WalletClientInfo = WalletClientInfo(
        wallet_rpc,
        wallet_state_manager.root_pubkey.get_fingerprint(),
        wallet_state_manager.config,
    )

    AMOUNT = uint64(1)
    async with wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, sign=False, push=False) as action_scope:
        await wallet.generate_signed_transaction(AMOUNT, bytes32([0] * 32), action_scope)
    [tx] = action_scope.side_effects.transactions

    runner = CliRunner()
    with runner.isolated_filesystem():
        with open("./temp-tb", "wb") as file:
            file.write(bytes(TransactionBundle([tx])))

        await GatherSigningInfoCMD(
            rpc_info=NeedsWalletRPC(client_info=client_info),
            sp_out=SPOut(
                translation="CHIP-0028",
                output_format="file",
                output_file=["./temp-si"],
            ),
            txs_in=TransactionsIn(transaction_file_in="./temp-tb"),
        ).run()

        await ExecuteSigningInstructionsCMD(
            rpc_info=NeedsWalletRPC(client_info=client_info),
            sp_in=SPIn(
                translation="CHIP-0028",
                signer_protocol_input=["./temp-si"],
            ),
            sp_out=SPOut(
                translation="CHIP-0028",
                output_format="file",
                output_file=["./temp-sr"],
            ),
        ).run()

        await ApplySignaturesCMD(
            rpc_info=NeedsWalletRPC(client_info=client_info),
            txs_in=TransactionsIn(transaction_file_in="./temp-tb"),
            sp_in=SPIn(
                translation="CHIP-0028",
                signer_protocol_input=["./temp-sr"],
            ),
            txs_out=TransactionsOut(transaction_file_out="./temp-stb"),
        ).run()

        await PushTransactionsCMD(
            rpc_info=NeedsWalletRPC(client_info=client_info),
            txs_in=TransactionsIn(transaction_file_in="./temp-stb"),
        ).run()

        await wallet_environments.process_pending_states(
            [
                WalletStateTransition(
                    pre_block_balance_updates={
                        1: {
                            "unconfirmed_wallet_balance": -1 * AMOUNT,
                            "<=#spendable_balance": -1 * AMOUNT,
                            "<=#max_send_amount": -1 * AMOUNT,
                            "pending_change": sum(c.amount for c in tx.removals) - AMOUNT,
                            "pending_coin_removal_count": 1,
                        }
                    },
                    post_block_balance_updates={
                        1: {
                            "confirmed_wallet_balance": -1 * AMOUNT,
                            "pending_change": -1 * (sum(c.amount for c in tx.removals) - AMOUNT),
                            "pending_coin_removal_count": -1,
                            "set_remainder": True,
                        },
                    },
                ),
            ]
        )


def test_signer_command_default_parsing() -> None:
    check_click_parsing(
        GatherSigningInfoCMD(
            rpc_info=NeedsWalletRPC(client_info=None, wallet_rpc_port=None, fingerprint=None),
            sp_out=SPOut(
                translation="none",
                output_format="hex",
                output_file=tuple(),
            ),
            txs_in=TransactionsIn(transaction_file_in="in"),
        ),
        "-i",
        "in",
    )

    check_click_parsing(
        ExecuteSigningInstructionsCMD(
            rpc_info=NeedsWalletRPC(client_info=None, wallet_rpc_port=None, fingerprint=None),
            sp_in=SPIn(
                translation="none",
                signer_protocol_input=("sp-in",),
            ),
            sp_out=SPOut(
                translation="none",
                output_format="hex",
                output_file=tuple(),
            ),
        ),
        "-p",
        "sp-in",
    )

    check_click_parsing(
        ApplySignaturesCMD(
            rpc_info=NeedsWalletRPC(client_info=None, wallet_rpc_port=None, fingerprint=None),
            txs_in=TransactionsIn(transaction_file_in="in"),
            sp_in=SPIn(
                translation="none",
                signer_protocol_input=("sp-in",),
            ),
            txs_out=TransactionsOut(transaction_file_out="out"),
        ),
        "-i",
        "in",
        "-o",
        "out",
        "-p",
        "sp-in",
    )

    check_click_parsing(
        PushTransactionsCMD(
            rpc_info=NeedsWalletRPC(client_info=None, wallet_rpc_port=None, fingerprint=None),
            txs_in=TransactionsIn(transaction_file_in="in"),
        ),
        "-i",
        "in",
    )


def test_transactions_in() -> None:
    @click.group()
    def cmd() -> None:
        pass

    @chia_command(cmd, "temp_cmd", "blah")
    class TempCMD(TransactionsIn):
        def run(self) -> None:
            assert self.transaction_bundle == TransactionBundle([STD_TX])

    runner = CliRunner()
    with runner.isolated_filesystem():
        with open("some file", "wb") as file:
            file.write(bytes(TransactionBundle([STD_TX])))

        result = runner.invoke(cmd, ["temp_cmd", "--transaction-file-in", "some file"], catch_exceptions=False)
        assert result.output == ""


def test_transactions_out() -> None:
    @click.group()
    def cmd() -> None:
        pass

    @chia_command(cmd, "temp_cmd", "blah")
    class TempCMD(TransactionsOut):
        def run(self) -> None:
            self.handle_transaction_output([STD_TX])

    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cmd, ["temp_cmd", "--transaction-file-out", "some file"], catch_exceptions=False)
        assert result.output == ""

        with open("some file", "rb") as file:
            file.read() == bytes(TransactionBundle([STD_TX]))


@clvm_streamable
@dataclasses.dataclass(frozen=True)
class FooCoin(Streamable):
    amount: uint64

    @staticmethod
    def from_wallet_api(_from: Coin) -> FooCoin:
        return FooCoin(_from.amount)

    @staticmethod
    def to_wallet_api(_from: FooCoin) -> Coin:
        return Coin(
            bytes32([0] * 32),
            bytes32([0] * 32),
            _from.amount,
        )


FOO_COIN_TRANSLATION = TranslationLayer(
    [
        TranslationLayerMapping(
            Coin,
            FooCoin,
            FooCoin.from_wallet_api,
            FooCoin.to_wallet_api,
        )
    ]
)


def test_signer_protocol_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(ALL_TRANSLATION_LAYERS, "CHIP-0028", FOO_COIN_TRANSLATION)

    @click.group()
    def cmd() -> None:
        pass

    coin = Coin(bytes32([0] * 32), bytes32([0] * 32), uint64(13))

    @chia_command(cmd, "temp_cmd", "blah")
    class TempCMD(SPIn):
        def run(self) -> None:
            assert self.read_sp_input(Coin) == [coin, coin]

    runner = CliRunner()
    with runner.isolated_filesystem():
        with open("some file", "wb") as file:
            file.write(byte_serialize_clvm_streamable(coin))

        with open("some file2", "wb") as file:
            file.write(byte_serialize_clvm_streamable(coin))

        result = runner.invoke(
            cmd,
            ["temp_cmd", "--signer-protocol-input", "some file", "--signer-protocol-input", "some file2"],
            catch_exceptions=False,
        )
        assert result.output == ""

    with runner.isolated_filesystem():
        with open("some file", "wb") as file:
            file.write(byte_serialize_clvm_streamable(coin, translation_layer=FOO_COIN_TRANSLATION))

            with open("some file2", "wb") as file:
                file.write(byte_serialize_clvm_streamable(coin, translation_layer=FOO_COIN_TRANSLATION))

        result = runner.invoke(
            cmd, ["temp_cmd", "--signer-protocol-input", "some file", "--signer-protocol-input", "some file2"]
        )
        assert result.exception is not None
        result = runner.invoke(
            cmd,
            [
                "temp_cmd",
                "--signer-protocol-input",
                "some file",
                "--signer-protocol-input",
                "some file2",
                "--translation",
                "CHIP-0028",
            ],
            catch_exceptions=False,
        )
        assert result.output == ""


def test_signer_protocol_out(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(ALL_TRANSLATION_LAYERS, "CHIP-0028", FOO_COIN_TRANSLATION)

    @click.group()
    def cmd() -> None:
        pass

    coin = Coin(bytes32([0] * 32), bytes32([0] * 32), uint64(0))
    coin_bytes = byte_serialize_clvm_streamable(coin)

    @chia_command(cmd, "temp_cmd", "blah")
    class TempCMD(SPOut):
        def run(self) -> None:
            self.handle_clvm_output([coin, coin])

    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cmd, ["temp_cmd", "--output-format", "hex"], catch_exceptions=False)
        assert result.output.strip() == coin_bytes.hex() + "\n" + coin_bytes.hex()

        result = runner.invoke(cmd, ["temp_cmd", "--output-format", "file"], catch_exceptions=False)
        assert result.output == "--output-format=file specified without any --output-file\n"

        result = runner.invoke(
            cmd, ["temp_cmd", "--output-format", "file", "--output-file", "some file"], catch_exceptions=False
        )
        assert "Incorrect number of file outputs specified" in result.output

        result = runner.invoke(
            cmd,
            ["temp_cmd", "--output-format", "file", "--output-file", "some file", "--output-file", "some file2"],
            catch_exceptions=False,
        )
        assert result.output == ""

        with open("some file", "rb") as file:
            file.read() == coin_bytes

        with open("some file2", "rb") as file:
            file.read() == coin_bytes

        result = runner.invoke(cmd, ["temp_cmd", "--output-format", "qr"], catch_exceptions=False)
        assert result.output != ""  # separate test for QrCodeDisplay

        result = runner.invoke(
            cmd, ["temp_cmd", "--output-format", "hex", "--translation", "CHIP-0028"], catch_exceptions=False
        )
        assert result.output.strip() != coin_bytes.hex()
        coin_hex = byte_serialize_clvm_streamable(coin, translation_layer=ALL_TRANSLATION_LAYERS["CHIP-0028"]).hex()
        assert result.output.strip() == coin_hex + "\n" + coin_hex


def test_qr_code_display() -> None:
    @click.group()
    def cmd() -> None:
        pass

    bytes_to_encode = b"foo bar qat qux bam bat"

    @chia_command(cmd, "temp_cmd", "blah")
    class TempCMD(QrCodeDisplay):
        def run(self) -> None:
            self.display_qr_codes([bytes_to_encode, bytes_to_encode])

    runner = CliRunner()
    result = runner.invoke(
        cmd,
        ["temp_cmd"],
        input="\n",
        catch_exceptions=False,
    )

    # Would be good to check eventually that the QR codes are valid but segno doesn't seem to provide that ATM
    assert result.output.count("Displaying QR Codes (1/2)") == 1
    assert result.output.count("Displaying QR Codes (2/2)") == 1
