from __future__ import annotations

import logging
import time
import types
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set, Tuple, Type

import pytest
from chia_rs import G1Element, G2Element, PrivateKey
from typing_extensions import Unpack

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import make_spend
from chia.types.signing_mode import SigningMode
from chia.types.spend_bundle import SpendBundle
from chia.util.ints import uint32, uint64
from chia.util.observation_root import ObservationRoot
from chia.wallet.conditions import Condition, CreateCoin, ReserveFee, parse_timelock_info
from chia.wallet.derivation_record import DerivationRecord
from chia.wallet.payment import Payment
from chia.wallet.signer_protocol import (
    PathHint,
    SignedTransaction,
    SigningInstructions,
    SigningResponse,
    Spend,
    SumHint,
    TransactionInfo,
)
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.compute_memos import compute_memos
from chia.wallet.util.transaction_type import TransactionType
from chia.wallet.util.tx_config import TXConfig
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_info import WalletInfo
from chia.wallet.wallet_protocol import GSTOptionalArgs, MainWalletProtocol
from chia.wallet.wallet_state_manager import WalletStateManager
from tests.environments.wallet import WalletStateTransition, WalletTestFramework

ACS: Program = Program.to(1)
ACS_PH: bytes32 = ACS.get_tree_hash()


class AnyoneCanSpend(Wallet):
    @staticmethod
    async def create(
        wallet_state_manager: Any,
        info: WalletInfo,
        name: str = __name__,
    ) -> AnyoneCanSpend:
        self = AnyoneCanSpend()
        self.wallet_state_manager = wallet_state_manager
        self.wallet_info = info
        self.wallet_id = info.id
        self.log = logging.getLogger(name)
        return self

    async def get_new_puzzle(self) -> Program:  # pragma: no cover
        return ACS

    async def get_new_puzzlehash(self) -> bytes32:  # pragma: no cover
        return ACS_PH

    async def generate_signed_transaction(
        self,
        amount: uint64,
        puzzle_hash: bytes32,
        tx_config: TXConfig,
        fee: uint64 = uint64(0),
        coins: Optional[Set[Coin]] = None,
        primaries: Optional[List[Payment]] = None,
        memos: Optional[List[bytes]] = None,
        puzzle_decorator_override: Optional[List[Dict[str, Any]]] = None,
        extra_conditions: Tuple[Condition, ...] = tuple(),
        **kwargs: Unpack[GSTOptionalArgs],
    ) -> List[TransactionRecord]:
        condition_list: List[Payment] = [] if primaries is None else primaries
        condition_list.append(Payment(puzzle_hash, amount, [] if memos is None else memos))
        non_change_amount: int = (
            sum(c.amount for c in condition_list)
            + sum(c.amount for c in extra_conditions if isinstance(c, CreateCoin))
            + fee
        )

        coins = await self.select_coins(uint64(non_change_amount), tx_config.coin_selection_config)
        total_amount = sum(c.amount for c in coins)

        condition_list.append(Payment(ACS_PH, uint64(total_amount - non_change_amount)))

        spend_bundle = SpendBundle(
            [
                make_spend(
                    coin,
                    ACS,
                    self.make_solution(condition_list, extra_conditions, fee) if i == 0 else Program.to([]),
                )
                for i, coin in enumerate(coins)
            ],
            G2Element(),
        )

        now = uint64(int(time.time()))
        return [
            TransactionRecord(
                confirmed_at_height=uint32(0),
                created_at_time=now,
                to_puzzle_hash=puzzle_hash,
                amount=uint64(non_change_amount),
                fee_amount=uint64(fee),
                confirmed=False,
                sent=uint32(0),
                spend_bundle=spend_bundle,
                additions=spend_bundle.additions(),
                removals=spend_bundle.removals(),
                wallet_id=self.id(),
                sent_to=[],
                trade_id=None,
                type=uint32(TransactionType.OUTGOING_TX.value),
                name=spend_bundle.name(),
                memos=list(compute_memos(spend_bundle).items()),
                valid_times=parse_timelock_info(extra_conditions),
            )
        ]

    def puzzle_for_pk(self, pubkey: G1Element) -> Program:  # pragma: no cover
        raise ValueError("This won't work")

    async def puzzle_for_puzzle_hash(self, puzzle_hash: bytes32) -> Program:
        if puzzle_hash == ACS_PH:
            return ACS
        else:
            raise ValueError("puzzle hash was not ACS_PH")  # pragma: no cover

    async def sign_message(self, message: str, puzzle_hash: bytes32, mode: SigningMode) -> Tuple[G1Element, G2Element]:
        raise ValueError("This won't work")  # pragma: no cover

    async def get_puzzle_hash(self, new: bool) -> bytes32:
        return ACS_PH

    async def apply_signatures(
        self, spends: List[Spend], signing_responses: List[SigningResponse]
    ) -> SignedTransaction:
        return SignedTransaction(
            TransactionInfo(spends),
            [],
        )

    async def execute_signing_instructions(
        self, signing_instructions: SigningInstructions, partial_allowed: bool = False
    ) -> List[SigningResponse]:
        if len(signing_instructions.targets) > 0:
            raise ValueError("This won't work")  # pragma: no cover
        else:
            return []

    async def path_hint_for_pubkey(self, pk: bytes) -> Optional[PathHint]:  # pragma: no cover
        return None

    async def sum_hint_for_pubkey(self, pk: bytes) -> Optional[SumHint]:  # pragma: no cover
        return None

    def make_solution(
        self,
        primaries: List[Payment],
        conditions: Tuple[Condition, ...] = tuple(),
        fee: uint64 = uint64(0),
        **kwargs: Any,
    ) -> Program:
        condition_list: List[Condition] = [CreateCoin(p.puzzle_hash, p.amount, p.memos) for p in primaries]
        condition_list.append(ReserveFee(fee))
        condition_list.extend(conditions)
        prog: Program = Program.to([c.to_program() for c in condition_list])
        return prog

    async def get_puzzle(self, new: bool) -> Program:  # pragma: no cover
        return ACS

    def puzzle_hash_for_pk(self, pubkey: G1Element) -> bytes32:  # pragma: no cover
        raise ValueError("This won't work")

    def require_derivation_paths(self) -> bool:
        return True

    async def match_hinted_coin(self, coin: Coin, hint: bytes32) -> bool:  # pragma: no cover
        if coin.puzzle_hash == ACS_PH or hint == ACS_PH:
            return True
        else:
            return False

    def handle_own_derivation(self) -> bool:
        return True

    def derivation_for_index(self, index: int) -> List[DerivationRecord]:
        return [
            DerivationRecord(
                uint32(index),
                ACS_PH,
                G1Element(),
                self.type(),
                uint32(self.id()),
                False,
            )
        ]


async def acs_setup(wallet_environments: WalletTestFramework, monkeypatch: pytest.MonkeyPatch) -> None:
    def get_main_wallet_driver(self: WalletStateManager, observation_root: ObservationRoot) -> Type[MainWalletProtocol]:
        return AnyoneCanSpend

    monkeypatch.setattr(
        WalletStateManager,
        "get_main_wallet_driver",
        types.MethodType(get_main_wallet_driver, WalletStateManager),
    )

    for env in wallet_environments.environments:
        pk = PrivateKey.from_bytes(
            bytes.fromhex("548dd25590a19f0a6a294560fc36f2900575fb9d1b2650e6fe80ad9abc1c4a60")
        ).get_g1()
        await env.node.keychain_proxy.add_key(bytes(pk).hex(), None, private=False)
        await env.restart(pk.get_fingerprint())


async def bls_got_setup(wallet_environments: WalletTestFramework, monkeypatch: pytest.MonkeyPatch) -> None:
    return None


@pytest.mark.parametrize(
    "wallet_environments",
    [
        {
            "num_environments": 1,
            "blocks_needed": [0],
        }
    ],
    indirect=True,
)
@pytest.mark.parametrize("setup_function", [acs_setup, bls_got_setup])
@pytest.mark.anyio
async def test_main_wallet(
    setup_function: Callable[[WalletTestFramework, pytest.MonkeyPatch], Awaitable[None]],
    wallet_environments: WalletTestFramework,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await setup_function(wallet_environments, monkeypatch)
    main_wallet: MainWalletProtocol = wallet_environments.environments[0].xch_wallet
    ph: bytes32 = await main_wallet.get_puzzle_hash(False)
    await wallet_environments.full_node.farm_blocks_to_puzzlehash(1, ph, guarantee_transaction_blocks=True)
    await wallet_environments.full_node.farm_blocks_to_puzzlehash(1, guarantee_transaction_blocks=True)
    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    1: {
                        "init": True,
                        "confirmed_wallet_balance": 2_000_000_000_000,
                        "unconfirmed_wallet_balance": 2_000_000_000_000,
                        "max_send_amount": 2_000_000_000_000,
                        "spendable_balance": 2_000_000_000_000,
                        "unspent_coin_count": 2,
                    }
                }
            )
        ]
    )
    txs: List[TransactionRecord] = await main_wallet.generate_signed_transaction(
        uint64(1_750_000_000_001),
        ph,
        wallet_environments.tx_config,
        fee=uint64(2),
        primaries=[Payment(ph, uint64(3))],
        extra_conditions=(CreateCoin(ph, uint64(4)),),
    )
    await main_wallet.wallet_state_manager.add_pending_transactions(txs)
    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    1: {
                        "unconfirmed_wallet_balance": -2,  # Only thing that actually went out was fee
                        "max_send_amount": -2_000_000_000_000,  # All coins are now pending
                        "spendable_balance": -2_000_000_000_000,  # All coins are now pending
                        "pending_change": 1_999_999_999_998,
                        "pending_coin_removal_count": 2,
                    }
                },
                post_block_balance_updates={
                    1: {
                        "confirmed_wallet_balance": -2,
                        "max_send_amount": 1_999_999_999_998,
                        "spendable_balance": 1_999_999_999_998,
                        "pending_change": -1_999_999_999_998,
                        "pending_coin_removal_count": -2,
                        # Minus: both farmed coins. Plus: Output, change, primary, extra_condition
                        "unspent_coin_count": -2 + 4,
                    }
                },
            )
        ]
    )

    # Miscellaneous checks
    assert [coin.puzzle_hash for tx in txs for coin in tx.removals] == [
        (await main_wallet.puzzle_for_puzzle_hash(coin.puzzle_hash)).get_tree_hash()
        for tx in txs
        for coin in tx.removals
    ]
