from __future__ import annotations

from typing import Optional

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
from chia.util.ints import uint32
from chia.wallet.derivation_record import DerivationRecord
from chia.wallet.derive_keys import master_sk_to_wallet_sk, master_sk_to_wallet_sk_unhardened
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import (
    DEFAULT_HIDDEN_PUZZLE_HASH,
    calculate_synthetic_secret_key,
    puzzle_hash_for_synthetic_public_key,
)
from chia.wallet.sign_coin_spends import sign_coin_spends
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet_puzzle_store import WalletPuzzleStore
from chia.wallet.wallet_state_manager import WalletStateManager

top_sk: PrivateKey = PrivateKey.from_bytes(bytes([1] * 32))
sk1_h: PrivateKey = master_sk_to_wallet_sk(top_sk, uint32(1))
sk2_h: PrivateKey = calculate_synthetic_secret_key(
    master_sk_to_wallet_sk(top_sk, uint32(2)), DEFAULT_HIDDEN_PUZZLE_HASH
)
sk1_u: PrivateKey = master_sk_to_wallet_sk_unhardened(top_sk, uint32(1))
sk2_u: PrivateKey = calculate_synthetic_secret_key(
    master_sk_to_wallet_sk_unhardened(top_sk, uint32(2)), DEFAULT_HIDDEN_PUZZLE_HASH
)
pk1_h: G1Element = sk1_h.get_g1()
pk2_h: G1Element = sk2_h.get_g1()
pk1_u: G1Element = sk1_u.get_g1()
pk2_u: G1Element = sk2_u.get_g1()
msg1: bytes = b"msg1"
msg2: bytes = b"msg2"

additional_data: bytes32 = bytes32(DEFAULT_CONSTANTS.AGG_SIG_ME_ADDITIONAL_DATA)

coin: Coin = Coin(bytes32([0] * 32), bytes32([0] * 32), 0)
puzzle = SerializedProgram.from_bytes(b"\x01")
solution_h = SerializedProgram.from_program(
    Program.to([[ConditionOpcode.AGG_SIG_UNSAFE, pk1_h, msg1], [ConditionOpcode.AGG_SIG_ME, pk2_h, msg2]])
)
solution_u = SerializedProgram.from_program(
    Program.to([[ConditionOpcode.AGG_SIG_UNSAFE, pk1_u, msg1], [ConditionOpcode.AGG_SIG_ME, pk2_u, msg2]])
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
async def test_sign_coin_spends() -> None:
    def derive_ph(pk: G1Element) -> bytes32:
        return bytes32([0] * 32)

    def pk_to_sk(pk: G1Element) -> Optional[PrivateKey]:
        if pk == pk1_h:
            return sk1_h
        return None

    def ph_to_sk(ph: bytes32) -> Optional[PrivateKey]:
        if ph == derive_ph(G1Element()):
            return sk2_h
        return None

    with pytest.raises(ValueError, match="no secret key"):
        await sign_coin_spends(
            [spend_h],
            pk_to_sk,
            lambda _: None,
            additional_data,
            1000000000,
            [derive_ph],
        )

    with pytest.raises(ValueError, match="no secret key"):
        await sign_coin_spends(
            [spend_h],
            lambda _: None,
            ph_to_sk,
            additional_data,
            1000000000,
            [derive_ph],
        )

    with pytest.raises(ValueError, match="no secret key"):
        await sign_coin_spends(
            [spend_h],
            pk_to_sk,
            ph_to_sk,
            additional_data,
            1000000000,
            [],
        )

    signature: G2Element = (
        await sign_coin_spends(
            [spend_h],
            pk_to_sk,
            ph_to_sk,
            additional_data,
            1000000000,
            [lambda _: bytes32([1] * 32), derive_ph],
        )
    ).aggregated_signature

    assert signature == AugSchemeMPL.aggregate(
        [
            AugSchemeMPL.sign(sk1_h, msg1),
            AugSchemeMPL.sign(sk2_h, msg2 + coin.name() + additional_data),
        ]
    )

    async def pk_to_sk_async(pk: G1Element) -> Optional[PrivateKey]:
        return pk_to_sk(pk)

    async def ph_to_sk_async(ph: bytes32) -> Optional[PrivateKey]:
        return ph_to_sk(ph)

    signature2: G2Element = (
        await sign_coin_spends(
            [spend_h],
            pk_to_sk_async,
            ph_to_sk_async,
            additional_data,
            1000000000,
            [derive_ph],
        )
    ).aggregated_signature
    assert signature2 == signature


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

            with pytest.raises(ValueError, match="no secret key"):
                await wsm.sign_transaction([spend_h])

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
                        puzzle_hash_for_synthetic_public_key(pk2_h),
                        G1Element(),
                        WalletType.STANDARD_WALLET,
                        uint32(1),
                        True,
                    )
                ]
            )

            signature: G2Element = (await wsm.sign_transaction([spend_h])).aggregated_signature
            assert signature == AugSchemeMPL.aggregate(
                [
                    AugSchemeMPL.sign(sk1_h, msg1),
                    AugSchemeMPL.sign(sk2_h, msg2 + coin.name() + additional_data),
                ]
            )

            with pytest.raises(ValueError, match="no secret key"):
                await wsm.sign_transaction([spend_u])

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
                        puzzle_hash_for_synthetic_public_key(pk2_u),
                        G1Element(),
                        WalletType.STANDARD_WALLET,
                        uint32(1),
                        False,
                    )
                ]
            )
            signature2: G2Element = (await wsm.sign_transaction([spend_u])).aggregated_signature
            assert signature2 == AugSchemeMPL.aggregate(
                [
                    AugSchemeMPL.sign(sk1_u, msg1),
                    AugSchemeMPL.sign(sk2_u, msg2 + coin.name() + additional_data),
                ]
            )
