from __future__ import annotations

import dataclasses
from typing import List, Optional, Tuple

import pytest
from chia_rs import AugSchemeMPL, G1Element, G2Element, PrivateKey

from chia.rpc.wallet_request_types import ApplySignatures, GatherSigningInfo, SubmitTransactions
from chia.rpc.wallet_rpc_client import WalletRpcClient
from chia.types.blockchain_format.coin import Coin as ConsensusCoin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend, make_spend
from chia.types.spend_bundle import SpendBundle
from chia.util.ints import uint64
from chia.util.streamable import Streamable, streamable
from chia.wallet.conditions import AggSigMe
from chia.wallet.derivation_record import DerivationRecord
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
from chia.wallet.util.clvm_streamable import (
    byte_deserialize_clvm_streamable,
    byte_serialize_clvm_streamable,
    clvm_streamable,
    json_deserialize_with_clvm_streamable,
    json_serialize_with_clvm_streamable,
    program_deserialize_clvm_streamable,
    program_serialize_clvm_streamable,
)
from chia.wallet.util.tx_config import DEFAULT_COIN_SELECTION_CONFIG
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_state_manager import WalletStateManager
from tests.environments.wallet import WalletStateTransition, WalletTestFramework


@clvm_streamable
@dataclasses.dataclass(frozen=True)
class Temp(Streamable):
    a: str


def test_basic_serialization() -> None:
    instance = Temp(a="1")
    assert program_serialize_clvm_streamable(instance) == Program.to(["1"])
    assert byte_serialize_clvm_streamable(instance).hex() == "ff3180"
    assert json_serialize_with_clvm_streamable(instance) == "ff3180"
    assert program_deserialize_clvm_streamable(Program.to(["1"]), Temp) == instance
    assert byte_deserialize_clvm_streamable(bytes.fromhex("ff3180"), Temp) == instance
    assert json_deserialize_with_clvm_streamable("ff3180", Temp) == instance


@streamable
@dataclasses.dataclass(frozen=True)
class OutsideStreamable(Streamable):
    inside: Temp
    a: str


@clvm_streamable
@dataclasses.dataclass(frozen=True)
class OutsideCLVM(Streamable):
    inside: Temp
    a: str


def test_nested_serialization() -> None:
    instance = OutsideStreamable(a="1", inside=Temp(a="1"))
    assert json_serialize_with_clvm_streamable(instance) == {"inside": "ff3180", "a": "1"}
    assert json_deserialize_with_clvm_streamable({"inside": "ff3180", "a": "1"}, OutsideStreamable) == instance
    assert OutsideStreamable.from_json_dict({"a": "1", "inside": {"a": "1"}}) == instance

    instance_clvm = OutsideCLVM(a="1", inside=Temp(a="1"))
    assert program_serialize_clvm_streamable(instance_clvm) == Program.to([["1"], "1"])
    assert byte_serialize_clvm_streamable(instance_clvm).hex() == "ffff3180ff3180"
    assert json_serialize_with_clvm_streamable(instance_clvm) == "ffff3180ff3180"
    assert program_deserialize_clvm_streamable(Program.to([["1"], "1"]), OutsideCLVM) == instance_clvm
    assert byte_deserialize_clvm_streamable(bytes.fromhex("ffff3180ff3180"), OutsideCLVM) == instance_clvm
    assert json_deserialize_with_clvm_streamable("ffff3180ff3180", OutsideCLVM) == instance_clvm


@streamable
@dataclasses.dataclass(frozen=True)
class Compound(Streamable):
    optional: Optional[Temp]
    list: List[Temp]


@clvm_streamable
@dataclasses.dataclass(frozen=True)
class CompoundCLVM(Streamable):
    optional: Optional[Temp]
    list: List[Temp]


def test_compound_type_serialization() -> None:
    # regular streamable + regular values
    instance = Compound(optional=Temp(a="1"), list=[Temp(a="1")])
    assert json_serialize_with_clvm_streamable(instance) == {"optional": "ff3180", "list": ["ff3180"]}
    assert json_deserialize_with_clvm_streamable({"optional": "ff3180", "list": ["ff3180"]}, Compound) == instance
    assert Compound.from_json_dict({"optional": {"a": "1"}, "list": [{"a": "1"}]}) == instance

    # regular streamable + falsey values
    instance = Compound(optional=None, list=[])
    assert json_serialize_with_clvm_streamable(instance) == {"optional": None, "list": []}
    assert json_deserialize_with_clvm_streamable({"optional": None, "list": []}, Compound) == instance
    assert Compound.from_json_dict({"optional": None, "list": []}) == instance

    # clvm streamable + regular values
    instance_clvm = CompoundCLVM(optional=Temp(a="1"), list=[Temp(a="1")])
    assert program_serialize_clvm_streamable(instance_clvm) == Program.to([[True, "1"], [["1"]]])
    assert byte_serialize_clvm_streamable(instance_clvm).hex() == "ffff01ff3180ffffff31808080"
    assert json_serialize_with_clvm_streamable(instance_clvm) == "ffff01ff3180ffffff31808080"
    assert program_deserialize_clvm_streamable(Program.to([[True, "1"], [["1"]]]), CompoundCLVM) == instance_clvm
    assert byte_deserialize_clvm_streamable(bytes.fromhex("ffff01ff3180ffffff31808080"), CompoundCLVM) == instance_clvm
    assert json_deserialize_with_clvm_streamable("ffff01ff3180ffffff31808080", CompoundCLVM) == instance_clvm

    # clvm streamable + falsey values
    instance_clvm = CompoundCLVM(optional=None, list=[])
    assert program_serialize_clvm_streamable(instance_clvm) == Program.to([[0], []])
    assert byte_serialize_clvm_streamable(instance_clvm).hex() == "ffff8080ff8080"
    assert json_serialize_with_clvm_streamable(instance_clvm) == "ffff8080ff8080"
    assert program_deserialize_clvm_streamable(Program.to([[0, 0], []]), CompoundCLVM) == instance_clvm
    assert byte_deserialize_clvm_streamable(bytes.fromhex("ffff8080ff8080"), CompoundCLVM) == instance_clvm
    assert json_deserialize_with_clvm_streamable("ffff8080ff8080", CompoundCLVM) == instance_clvm

    with pytest.raises(ValueError, match="@clvm_streamable"):

        @clvm_streamable
        @dataclasses.dataclass(frozen=True)
        class DoesntWork(Streamable):
            optional: Tuple[str]


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

    derivation_record: Optional[
        DerivationRecord
    ] = await wallet_state_manager.puzzle_store.get_derivation_record_for_puzzle_hash(coin.puzzle_hash)
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
        not_our_signing_instructions = dataclasses.replace(
            not_our_signing_instructions,
            key_hints=dataclasses.replace(
                not_our_signing_instructions.key_hints,
                sum_hints=[
                    *not_our_signing_instructions.key_hints.sum_hints,
                    SumHint([bytes(not_our_pubkey)], b"", bytes(G1Element())),
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
