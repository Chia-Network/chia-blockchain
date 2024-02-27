from __future__ import annotations

import re

import pytest
from chia_rs import AugSchemeMPL, G1Element, G2Element, PrivateKey

from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.serialized_program import SerializedProgram
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend, make_spend
from chia.types.condition_opcodes import ConditionOpcode
from chia.util.db_wrapper import DBWrapper2, manage_connection
from chia.util.ints import uint32, uint64
from chia.wallet.derivation_record import DerivationRecord
from chia.wallet.derive_keys import master_sk_to_wallet_sk, master_sk_to_wallet_sk_unhardened
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import (
    DEFAULT_HIDDEN_PUZZLE_HASH,
    calculate_synthetic_secret_key,
    puzzle_hash_for_synthetic_public_key,
)
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_puzzle_store import WalletPuzzleStore
from chia.wallet.wallet_state_manager import WalletStateManager
from chia.wallet.wallet_user_store import WalletUserStore

top_sk: PrivateKey = PrivateKey.from_bytes(bytes([1] * 32))
sk1_h: PrivateKey = master_sk_to_wallet_sk(top_sk, uint32(1))
sk2_h: PrivateKey = master_sk_to_wallet_sk(top_sk, uint32(2))
sk2_h_synth: PrivateKey = calculate_synthetic_secret_key(sk2_h, DEFAULT_HIDDEN_PUZZLE_HASH)
sk1_u: PrivateKey = master_sk_to_wallet_sk_unhardened(top_sk, uint32(1))
sk2_u: PrivateKey = master_sk_to_wallet_sk(top_sk, uint32(2))
sk2_u_synth: PrivateKey = calculate_synthetic_secret_key(sk2_u, DEFAULT_HIDDEN_PUZZLE_HASH)
pk1_h: G1Element = sk1_h.get_g1()
pk2_h: G1Element = sk2_h.get_g1()
pk2_h_synth: G1Element = sk2_h_synth.get_g1()
pk1_u: G1Element = sk1_u.get_g1()
pk2_u: G1Element = sk2_u.get_g1()
pk2_u_synth: G1Element = sk2_u_synth.get_g1()
msg1: bytes = b"msg1"
msg2: bytes = b"msg2"

additional_data: bytes32 = bytes32(DEFAULT_CONSTANTS.AGG_SIG_ME_ADDITIONAL_DATA)

coin: Coin = Coin(bytes32([0] * 32), bytes32([0] * 32), uint64(0))
puzzle = SerializedProgram.from_bytes(b"\x01")
solution_h = SerializedProgram.from_program(
    Program.to([[ConditionOpcode.AGG_SIG_UNSAFE, pk1_h, msg1], [ConditionOpcode.AGG_SIG_ME, pk2_h_synth, msg2]])
)
solution_u = SerializedProgram.from_program(
    Program.to([[ConditionOpcode.AGG_SIG_UNSAFE, pk1_u, msg1], [ConditionOpcode.AGG_SIG_ME, pk2_u_synth, msg2]])
)
spend_h: CoinSpend = make_spend(
    coin,
    puzzle,
    solution_h,
)
spend_u: CoinSpend = make_spend(
    coin,
    puzzle,
    solution_u,
)


@pytest.mark.anyio
async def test_wsm_sign_transaction() -> None:
    async with manage_connection("file:temp.db?mode=memory&cache=shared", uri=True, name="writer") as writer_conn:
        async with manage_connection("file:temp.db?mode=memory&cache=shared", uri=True, name="reader") as reader_conn:
            wsm = WalletStateManager()
            db = DBWrapper2(writer_conn)
            await db.add_connection(reader_conn)
            wsm.puzzle_store = await WalletPuzzleStore.create(db)
            wsm.constants = DEFAULT_CONSTANTS
            wsm.private_key = top_sk
            wsm.root_pubkey = top_sk.get_g1()
            wsm.user_store = await WalletUserStore.create(db)
            wallet_info = await wsm.user_store.get_wallet_by_id(1)
            assert wallet_info is not None
            wsm.main_wallet = await Wallet.create(wsm, wallet_info)

            with pytest.raises(
                ValueError, match=re.escape(f"Pubkey {pk1_h.get_fingerprint()} not found (or path/sum hinted to)")
            ):
                await wsm.sign_bundle([spend_h])

            await wsm.puzzle_store.add_derivation_paths(
                [
                    DerivationRecord(
                        uint32(1),
                        bytes32([0] * 32),
                        pk1_h,
                        WalletType.STANDARD_WALLET,
                        uint32(1),
                        True,
                    )
                ]
            )

            await wsm.puzzle_store.add_derivation_paths(
                [
                    DerivationRecord(
                        uint32(2),
                        puzzle_hash_for_synthetic_public_key(pk2_h_synth),
                        pk2_h,
                        WalletType.STANDARD_WALLET,
                        uint32(1),
                        True,
                    )
                ]
            )

            signature: G2Element = ((await wsm.sign_bundle([spend_h]))[0]).aggregated_signature
            assert signature == AugSchemeMPL.aggregate(
                [
                    AugSchemeMPL.sign(sk1_h, msg1),
                    AugSchemeMPL.sign(sk2_h_synth, msg2 + coin.name() + additional_data),
                ]
            )

            with pytest.raises(
                ValueError, match=re.escape(f"Pubkey {pk1_u.get_fingerprint()} not found (or path/sum hinted to)")
            ):
                await wsm.sign_bundle([spend_u])

            await wsm.puzzle_store.add_derivation_paths(
                [
                    DerivationRecord(
                        uint32(1),
                        bytes32([0] * 32),
                        pk1_u,
                        WalletType.STANDARD_WALLET,
                        uint32(1),
                        False,
                    )
                ]
            )

            await wsm.puzzle_store.add_derivation_paths(
                [
                    DerivationRecord(
                        uint32(2),
                        puzzle_hash_for_synthetic_public_key(pk2_u_synth),
                        pk2_u,
                        WalletType.STANDARD_WALLET,
                        uint32(1),
                        False,
                    )
                ]
            )
            signature2: G2Element = ((await wsm.sign_bundle([spend_u]))[0]).aggregated_signature
            assert signature2 == AugSchemeMPL.aggregate(
                [
                    AugSchemeMPL.sign(sk1_u, msg1),
                    AugSchemeMPL.sign(sk2_u_synth, msg2 + coin.name() + additional_data),
                ]
            )
