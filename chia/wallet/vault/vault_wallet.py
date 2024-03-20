from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

from chia_rs import G1Element, G2Element
from ecdsa.keys import SigningKey
from typing_extensions import Unpack

from chia.protocols.wallet_protocol import CoinState
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend, make_spend
from chia.types.signing_mode import SigningMode
from chia.types.spend_bundle import SpendBundle
from chia.util.hash import std_hash
from chia.util.ints import uint32, uint64, uint128
from chia.wallet.coin_selection import select_coins
from chia.wallet.conditions import Condition, CreateCoin, CreatePuzzleAnnouncement, parse_timelock_info
from chia.wallet.derivation_record import DerivationRecord
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.payment import Payment
from chia.wallet.puzzles.p2_conditions import puzzle_for_conditions, solution_for_conditions
from chia.wallet.signer_protocol import (
    PathHint,
    SignedTransaction,
    SigningInstructions,
    SigningResponse,
    SigningTarget,
    Spend,
    SumHint,
    TransactionInfo,
)
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.compute_hints import compute_spend_hints_and_additions
from chia.wallet.util.transaction_type import TransactionType
from chia.wallet.util.tx_config import CoinSelectionConfig, TXConfig
from chia.wallet.util.wallet_sync_utils import fetch_coin_spend
from chia.wallet.util.wallet_types import WalletIdentifier
from chia.wallet.vault.vault_drivers import (
    construct_p2_delegated_secp,
    construct_vault_merkle_tree,
    get_p2_singleton_puzzle,
    get_p2_singleton_puzzle_hash,
    get_recovery_finish_puzzle,
    get_recovery_inner_puzzle,
    get_recovery_puzzle,
    get_recovery_solution,
    get_vault_full_puzzle,
    get_vault_full_solution,
    get_vault_hidden_puzzle_with_index,
    get_vault_inner_puzzle,
    get_vault_inner_puzzle_hash,
    get_vault_inner_solution,
    get_vault_proof,
    match_vault_puzzle,
)
from chia.wallet.vault.vault_info import RecoveryInfo, VaultInfo
from chia.wallet.vault.vault_root import VaultRoot
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_info import WalletInfo
from chia.wallet.wallet_protocol import GSTOptionalArgs


@dataclass
class Vault(Wallet):
    _vault_info: Optional[VaultInfo] = None

    @property
    def vault_info(self) -> VaultInfo:
        if self._vault_info is None:
            raise ValueError("VaultInfo is not set")
        return self._vault_info

    @property
    def launcher_id(self) -> bytes32:
        assert isinstance(self.wallet_state_manager.observation_root, VaultRoot)
        return bytes32(self.wallet_state_manager.observation_root.launcher_id)

    @staticmethod
    async def create(
        wallet_state_manager: Any,
        info: WalletInfo,
        name: str = __name__,
    ) -> Vault:
        self = Vault()
        self.wallet_state_manager = wallet_state_manager
        self.wallet_info = info
        self.wallet_id = info.id
        self.log = logging.getLogger(name)
        return self

    async def get_new_puzzle(self) -> Program:
        dr = await self.wallet_state_manager.get_unused_derivation_record(self.id())
        hidden_puzzle_hash = get_vault_hidden_puzzle_with_index(dr.index).get_tree_hash()
        puzzle = get_vault_inner_puzzle(
            self.vault_info.pubkey,
            self.wallet_state_manager.constants.GENESIS_CHALLENGE,
            hidden_puzzle_hash,
            self.vault_info.recovery_info.bls_pk,
            self.vault_info.recovery_info.timelock,
        )
        return puzzle

    async def get_new_puzzlehash(self) -> bytes32:
        puzzle = await self.get_new_puzzle()
        return puzzle.get_tree_hash()

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
        """
        Creates Un-signed transactions to be passed into signer.
        """
        if primaries is None:
            non_change_amount: int = amount
        else:
            non_change_amount = amount + sum(p.amount for p in primaries)

        non_change_amount += sum(c.amount for c in extra_conditions if isinstance(c, CreateCoin))
        coin_spends = await self._generate_unsigned_transaction(
            amount,
            puzzle_hash,
            tx_config,
            fee=fee,
            coins=coins,
            primaries_input=primaries,
            memos=memos,
            negative_change_allowed=kwargs.get("negative_change_allowed", False),
            puzzle_decorator_override=puzzle_decorator_override,
            extra_conditions=extra_conditions,
        )
        spend_bundle = SpendBundle(coin_spends, G2Element())

        tx_record = TransactionRecord(
            confirmed_at_height=uint32(0),
            created_at_time=uint64(int(time.time())),
            to_puzzle_hash=puzzle_hash,
            amount=uint64(non_change_amount),
            fee_amount=fee,
            confirmed=False,
            sent=uint32(0),
            spend_bundle=spend_bundle,
            additions=[],
            removals=[],
            wallet_id=self.id(),
            sent_to=[],
            memos=[],
            trade_id=None,
            type=uint32(TransactionType.OUTGOING_TX.value),
            name=spend_bundle.name(),
            valid_times=parse_timelock_info(tuple()),
        )
        return [tx_record]

    async def generate_p2_singleton_spends(
        self,
        amount: uint64,
        tx_config: TXConfig,
        coins: Optional[Set[Coin]] = None,
    ) -> List[CoinSpend]:
        total_balance = await self.get_spendable_balance()
        if coins is None:
            if amount > total_balance:
                raise ValueError(
                    f"Can't spend more than wallet balance: {total_balance} mojos, tried to spend: {amount} mojos"
                )
            coins = await self.select_coins(
                uint64(amount),
                tx_config.coin_selection_config,
            )
        assert len(coins) > 0

        p2_singleton_puzzle: Program = get_p2_singleton_puzzle(self.launcher_id)

        spends: List[CoinSpend] = []
        for coin in list(coins):
            p2_singleton_solution: Program = Program.to([self.vault_info.inner_puzzle_hash, coin.name()])
            spends.append(make_spend(coin, p2_singleton_puzzle, p2_singleton_solution))

        return spends

    async def _generate_unsigned_transaction(
        self,
        amount: uint64,
        newpuzzlehash: bytes32,
        tx_config: TXConfig,
        fee: uint64 = uint64(0),
        origin_id: Optional[bytes32] = None,
        coins: Optional[Set[Coin]] = None,
        primaries_input: Optional[List[Payment]] = None,
        memos: Optional[List[bytes]] = None,
        negative_change_allowed: bool = False,
        puzzle_decorator_override: Optional[List[Dict[str, Any]]] = None,
        extra_conditions: Tuple[Condition, ...] = tuple(),
    ) -> List[CoinSpend]:
        primaries = []
        if primaries_input is not None:
            primaries.extend(primaries_input)
        total_amount = (
            amount
            + sum(primary.amount for primary in primaries)
            + fee
            + sum(c.amount for c in extra_conditions if isinstance(c, CreateCoin))
        )

        p2_singleton_spends = await self.generate_p2_singleton_spends(uint64(total_amount), tx_config, coins=coins)

        coins = {spend.coin for spend in p2_singleton_spends}
        spend_value = sum([coin.amount for coin in coins])
        change = spend_value - total_amount
        assert change >= 0
        if change > 0:
            change_puzzle_hash: bytes32 = get_p2_singleton_puzzle_hash(self.launcher_id)
            primaries.append(Payment(change_puzzle_hash, uint64(change)))

        conditions = [primary.as_condition() for primary in primaries]
        next_puzzle_hash = (
            self.vault_info.coin.puzzle_hash if tx_config.reuse_puzhash else (await self.get_new_puzzlehash())
        )
        recreate_vault_condition = CreateCoin(
            next_puzzle_hash, uint64(self.vault_info.coin.amount), memos=[next_puzzle_hash]
        ).to_program()
        conditions.append(recreate_vault_condition)
        announcements = [CreatePuzzleAnnouncement(spend.coin.name()).to_program() for spend in p2_singleton_spends]
        conditions.extend(announcements)

        delegated_puzzle = puzzle_for_conditions(conditions)
        delegated_solution = solution_for_conditions(conditions)

        secp_puzzle = construct_p2_delegated_secp(
            self.vault_info.pubkey,
            self.wallet_state_manager.constants.GENESIS_CHALLENGE,
            self.vault_info.hidden_puzzle_hash,
        )
        vault_inner_puzzle = get_vault_inner_puzzle(
            self.vault_info.pubkey,
            self.wallet_state_manager.constants.GENESIS_CHALLENGE,
            self.vault_info.hidden_puzzle_hash,
            self.vault_info.recovery_info.bls_pk,
            self.vault_info.recovery_info.timelock,
        )

        secp_solution = Program.to(
            [
                delegated_puzzle,
                delegated_solution,
                None,  # Slot for signed message
                self.vault_info.coin.name(),
            ]
        )
        if self.vault_info.is_recoverable:
            recovery_puzzle_hash = get_recovery_puzzle(
                secp_puzzle.get_tree_hash(),
                self.vault_info.recovery_info.bls_pk,
                self.vault_info.recovery_info.timelock,
            ).get_tree_hash()
            merkle_tree = construct_vault_merkle_tree(secp_puzzle.get_tree_hash(), recovery_puzzle_hash)
        else:
            merkle_tree = construct_vault_merkle_tree(secp_puzzle.get_tree_hash())
        proof = get_vault_proof(merkle_tree, secp_puzzle.get_tree_hash())
        vault_inner_solution = get_vault_inner_solution(secp_puzzle, secp_solution, proof)

        full_puzzle = get_vault_full_puzzle(self.launcher_id, vault_inner_puzzle)
        full_solution = get_vault_full_solution(
            self.vault_info.lineage_proof,
            uint64(self.vault_info.coin.amount),
            vault_inner_solution,
        )

        vault_spend = make_spend(self.vault_info.coin, full_puzzle, full_solution)
        all_spends = [*p2_singleton_spends, vault_spend]

        return all_spends

    def puzzle_for_pk(self, pubkey: G1Element) -> Program:
        raise NotImplementedError("vault wallet")

    async def puzzle_for_puzzle_hash(self, puzzle_hash: bytes32) -> Program:
        raise NotImplementedError("vault wallet")

    async def sign_message(self, message: str, puzzle_hash: bytes32, mode: SigningMode) -> Tuple[G1Element, G2Element]:
        raise NotImplementedError("vault wallet")

    async def get_puzzle_hash(self, new: bool) -> bytes32:
        if new:
            return await self.get_new_puzzlehash()
        else:
            record: Optional[
                DerivationRecord
            ] = await self.wallet_state_manager.get_current_derivation_record_for_wallet(self.id())
            if record is None:
                return await self.get_new_puzzlehash()
            return record.puzzle_hash

    async def gather_signing_info(self, coin_spends: List[Spend]) -> SigningInstructions:
        pk = self.vault_info.pubkey
        # match the vault puzzle
        for spend in coin_spends:
            mod, curried_args = spend.puzzle.uncurry()
            if match_vault_puzzle(mod, curried_args):
                vault_spend = spend
                break
        inner_sol = vault_spend.solution.at("rrf")
        secp_puz = inner_sol.at("rf")
        secp_sol = inner_sol.at("rrf")
        _, secp_args = secp_puz.uncurry()
        genesis_challenge = secp_args.at("f").as_atom()
        hidden_puzzle_hash = secp_args.at("rrf").as_atom()
        delegated_puzzle_hash = secp_sol.at("f").get_tree_hash()
        coin_id = secp_sol.at("rrrf").as_atom()
        message = delegated_puzzle_hash + coin_id + genesis_challenge + hidden_puzzle_hash
        fingerprint = self.wallet_state_manager.observation_root.get_fingerprint().to_bytes(4, "big")
        target = SigningTarget(fingerprint, message, std_hash(pk + message))
        sig_info = SigningInstructions(
            await self.wallet_state_manager.key_hints_for_pubkeys([pk]),
            [target],
        )
        return sig_info

    async def apply_signatures(
        self, spends: List[Spend], signing_responses: List[SigningResponse]
    ) -> SignedTransaction:
        signed_spends = []
        for spend in spends:
            mod, curried_args = spend.puzzle.uncurry()
            if match_vault_puzzle(mod, curried_args):
                new_sol = spend.solution.replace(rrfrrfrrf=signing_responses[0].signature)
                signed_spends.append(Spend(spend.coin, spend.puzzle, new_sol))
            else:
                signed_spends.append(spend)
        return SignedTransaction(
            TransactionInfo(signed_spends),
            [],
        )

    async def execute_signing_instructions(
        self, signing_instructions: SigningInstructions, partial_allowed: bool = False
    ) -> List[SigningResponse]:
        root_pubkey = self.wallet_state_manager.observation_root
        sk: SigningKey = self.wallet_state_manager.config["test_sk"]  # Temporary access to private key
        sk_lookup: Dict[int, SigningKey] = {root_pubkey.get_fingerprint(): sk}
        responses: List[SigningResponse] = []

        # We don't need to expand path and sum hints since vault signer always uses the same keys
        # so just sign the targets
        for target in signing_instructions.targets:
            fingerprint: int = int.from_bytes(target.fingerprint, "big")
            if fingerprint not in sk_lookup:
                raise ValueError(f"Pubkey {fingerprint} not found")
            responses.append(
                SigningResponse(
                    sk_lookup[fingerprint].sign_deterministic(target.message),
                    target.hook,
                )
            )

        return responses

    async def path_hint_for_pubkey(self, pk: bytes) -> Optional[PathHint]:
        return None

    async def sum_hint_for_pubkey(self, pk: bytes) -> Optional[SumHint]:
        return None

    def make_solution(
        self,
        primaries: List[Payment],
        conditions: Tuple[Condition, ...] = tuple(),
        fee: uint64 = uint64(0),
        **kwargs: Any,
    ) -> Program:
        assert fee >= 0
        coin_id = kwargs.get("coin_id")
        if coin_id is None:
            raise ValueError("Vault p2_singleton solutions require a coin id")
        p2_singleton_solution: Program = Program.to([self.vault_info.inner_puzzle_hash, coin_id])
        return p2_singleton_solution

    async def get_puzzle(self, new: bool) -> Program:
        if new:
            return await self.get_new_puzzle()
        else:
            record: Optional[
                DerivationRecord
            ] = await self.wallet_state_manager.get_current_derivation_record_for_wallet(self.id())
            if record is None:
                return await self.get_new_puzzle()
            puzzle = construct_p2_delegated_secp(
                record.pubkey, self.wallet_state_manager.constants.GENESIS_CHALLENGE, record.puzzle_hash
            )
            return puzzle

    def puzzle_hash_for_pk(self, pubkey: G1Element) -> bytes32:
        raise ValueError("This won't work")

    def require_derivation_paths(self) -> bool:
        if getattr(self, "_vault_info", None):
            return True
        return False

    async def match_hinted_coin(self, coin: Coin, hint: bytes32) -> bool:
        wallet_identifier: Optional[
            WalletIdentifier
        ] = await self.wallet_state_manager.puzzle_store.get_wallet_identifier_for_puzzle_hash(hint)
        if wallet_identifier:
            return True
        return False

    def handle_own_derivation(self) -> bool:
        return True

    def get_p2_singleton_puzzle_hash(self) -> bytes32:
        return get_p2_singleton_puzzle_hash(self.launcher_id)

    async def select_coins(self, amount: uint64, coin_selection_config: CoinSelectionConfig) -> Set[Coin]:
        unconfirmed_removals: Dict[bytes32, Coin] = await self.wallet_state_manager.unconfirmed_removals_for_wallet(
            self.id()
        )
        puzhash = self.get_p2_singleton_puzzle_hash()
        records = await self.wallet_state_manager.coin_store.get_coin_records_by_puzzle_hash(puzhash)
        assert records is not None
        spendable_amount = uint128(sum([rec.coin.amount for rec in records]))
        coins = await select_coins(
            spendable_amount,
            coin_selection_config,
            records,
            unconfirmed_removals,
            self.log,
            uint128(amount),
        )
        return coins

    def derivation_for_index(self, index: int) -> List[DerivationRecord]:
        hidden_puzzle = get_vault_hidden_puzzle_with_index(uint32(index))
        hidden_puzzle_hash = hidden_puzzle.get_tree_hash()
        inner_puzzle_hash = get_vault_inner_puzzle_hash(
            self.vault_info.pubkey,
            self.wallet_state_manager.constants.GENESIS_CHALLENGE,
            hidden_puzzle_hash,
            self.vault_info.recovery_info.bls_pk,
            self.vault_info.recovery_info.timelock,
        )
        record = DerivationRecord(
            uint32(index), inner_puzzle_hash, self.vault_info.pubkey, self.type(), self.id(), False
        )
        return [record]

    async def create_recovery_spends(self) -> List[TransactionRecord]:
        """
        Returns two tx records
        1. Recover the vault which can be taken to the appropriate BLS wallet for signing
        2. Complete the recovery after the timelock has elapsed
        """
        assert self.vault_info.recovery_info is not None
        wallet_node: Any = self.wallet_state_manager.wallet_node
        peer = wallet_node.get_full_node_peer()
        assert peer is not None
        # 1. Generate the recovery spend
        # Get the current vault coin, ensure it's unspent
        vault_coin = self.vault_info.coin
        amount = uint64(self.vault_info.coin.amount)
        vault_coin_state = (await wallet_node.get_coin_state([vault_coin.name()], peer))[0]
        assert vault_coin_state.spent_height is None
        # Generate the current inner puzzle
        inner_puzzle = get_vault_inner_puzzle(
            self.vault_info.pubkey,
            self.wallet_state_manager.constants.GENESIS_CHALLENGE,
            self.vault_info.hidden_puzzle_hash,
            self.vault_info.recovery_info.bls_pk,
            self.vault_info.recovery_info.timelock,
        )
        assert inner_puzzle.get_tree_hash() == self.vault_info.inner_puzzle_hash

        secp_puzzle_hash = construct_p2_delegated_secp(
            self.vault_info.pubkey,
            self.wallet_state_manager.constants.GENESIS_CHALLENGE,
            self.vault_info.hidden_puzzle_hash,
        ).get_tree_hash()

        recovery_puzzle = get_recovery_puzzle(
            secp_puzzle_hash, self.vault_info.recovery_info.bls_pk, self.vault_info.recovery_info.timelock
        )
        recovery_puzzle_hash = recovery_puzzle.get_tree_hash()
        assert isinstance(self.vault_info.recovery_info.bls_pk, G1Element)
        recovery_solution = get_recovery_solution(amount, self.vault_info.recovery_info.bls_pk)

        merkle_tree = construct_vault_merkle_tree(secp_puzzle_hash, recovery_puzzle_hash)
        proof = get_vault_proof(merkle_tree, recovery_puzzle_hash)
        inner_solution = get_vault_inner_solution(recovery_puzzle, recovery_solution, proof)

        full_puzzle = get_vault_full_puzzle(self.launcher_id, inner_puzzle)
        assert full_puzzle.get_tree_hash() == vault_coin.puzzle_hash

        full_solution = get_vault_full_solution(self.vault_info.lineage_proof, amount, inner_solution)
        recovery_spend = SpendBundle([make_spend(vault_coin, full_puzzle, full_solution)], G2Element())

        # 2. Generate the Finish Recovery Spend
        assert isinstance(self.vault_info.recovery_info.bls_pk, G1Element)
        assert isinstance(self.vault_info.recovery_info.timelock, uint64)
        recovery_finish_puzzle = get_recovery_finish_puzzle(
            self.vault_info.recovery_info.bls_pk, self.vault_info.recovery_info.timelock, amount
        )
        recovery_finish_solution = Program.to([])
        recovery_inner_puzzle = get_recovery_inner_puzzle(secp_puzzle_hash, recovery_finish_puzzle.get_tree_hash())
        full_recovery_puzzle = get_vault_full_puzzle(self.launcher_id, recovery_inner_puzzle)
        recovery_coin = Coin(self.vault_info.coin.name(), full_recovery_puzzle.get_tree_hash(), amount)
        recovery_solution = get_vault_inner_solution(recovery_finish_puzzle, recovery_finish_solution, proof)
        lineage = LineageProof(self.vault_info.coin.name(), inner_puzzle.get_tree_hash(), amount)
        full_recovery_solution = get_vault_full_solution(lineage, amount, recovery_solution)
        finish_spend = SpendBundle(
            [make_spend(recovery_coin, full_recovery_puzzle, full_recovery_solution)], G2Element()
        )

        # make the tx records
        recovery_tx = TransactionRecord(
            confirmed_at_height=uint32(0),
            created_at_time=uint64(int(time.time())),
            to_puzzle_hash=full_puzzle.get_tree_hash(),
            amount=amount,
            fee_amount=uint64(0),
            confirmed=False,
            sent=uint32(0),
            spend_bundle=recovery_spend,
            additions=recovery_spend.additions(),
            removals=recovery_spend.removals(),
            wallet_id=self.id(),
            sent_to=[],
            memos=[],
            trade_id=None,
            type=uint32(TransactionType.OUTGOING_TX.value),
            name=recovery_spend.name(),
            valid_times=parse_timelock_info(tuple()),
        )

        finish_tx = TransactionRecord(
            confirmed_at_height=uint32(0),
            created_at_time=uint64(int(time.time())),
            to_puzzle_hash=full_puzzle.get_tree_hash(),
            amount=amount,
            fee_amount=uint64(0),
            confirmed=False,
            sent=uint32(0),
            spend_bundle=finish_spend,
            additions=finish_spend.additions(),
            removals=finish_spend.removals(),
            wallet_id=self.id(),
            sent_to=[],
            memos=[],
            trade_id=None,
            type=uint32(TransactionType.OUTGOING_TX.value),
            name=finish_spend.name(),
            valid_times=parse_timelock_info(tuple()),
        )

        return [recovery_tx, finish_tx]

    async def sync_vault_launcher(self) -> None:
        wallet_node: Any = self.wallet_state_manager.wallet_node
        peer = wallet_node.get_full_node_peer()
        assert peer is not None

        assert isinstance(self.wallet_state_manager.observation_root, VaultRoot)

        coin_states = await wallet_node.get_coin_state([self.launcher_id], peer)
        if not coin_states:
            raise ValueError(f"No coin found for launcher id: {self.launcher_id}.")
        coin_state: CoinState = coin_states[0]
        # parent_state: CoinState = (await wallet_node.get_coin_state([coin_state.coin.parent_coin_info], peer))[0]

        assert coin_state.spent_height is not None
        launcher_spend = await fetch_coin_spend(uint32(coin_state.spent_height), coin_state.coin, peer)
        launcher_solution = launcher_spend.solution.to_program()

        is_recoverable = False
        bls_pk = None
        timelock = None
        memos = launcher_solution.at("rrf")
        secp_pk = memos.at("f").as_atom()
        hidden_puzzle_hash = bytes32(memos.at("rf").as_atom())
        if memos.list_len() == 4:
            bls_pk = G1Element.from_bytes(memos.at("rrf").as_atom())
            timelock = uint64(memos.at("rrrf").as_int())
            recovery_info = RecoveryInfo(bls_pk, timelock)
            is_recoverable = True
        else:
            recovery_info = RecoveryInfo(None, None)
            is_recoverable = False
        inner_puzzle = get_vault_inner_puzzle(
            secp_pk, self.wallet_state_manager.constants.GENESIS_CHALLENGE, hidden_puzzle_hash, bls_pk, timelock
        )
        inner_puzzle_hash = inner_puzzle.get_tree_hash()
        lineage_proof = LineageProof(coin_state.coin.parent_coin_info, None, uint64(coin_state.coin.amount))
        vault_puzzle_hash = get_vault_full_puzzle(coin_state.coin.name(), inner_puzzle).get_tree_hash()
        vault_coin = Coin(self.launcher_id, vault_puzzle_hash, uint64(coin_state.coin.amount))
        vault_info = VaultInfo(
            vault_coin,
            secp_pk,
            hidden_puzzle_hash,
            inner_puzzle_hash,
            lineage_proof,
            is_recoverable,
            recovery_info,
        )
        await self.save_info(vault_info)
        await self.wallet_state_manager.create_more_puzzle_hashes()

        # subscribe to p2_singleton puzzle hash
        p2_puzzle_hash = self.get_p2_singleton_puzzle_hash()
        await self.wallet_state_manager.add_interested_puzzle_hashes([p2_puzzle_hash], [self.id()])

        # add the singleton record to store
        await self.wallet_state_manager.singleton_store.add_eve_record(
            self.id(),
            coin_state.coin,
            launcher_spend,
            inner_puzzle_hash,
            lineage_proof,
            uint32(coin_state.spent_height) if coin_state.spent_height else uint32(0),
            pending=False,
            custom_data=bytes(json.dumps(vault_info.to_json_dict()), "utf-8"),
        )

    async def update_vault_singleton(
        self, next_inner_puzzle: Program, coin_spend: CoinSpend, coin_state: CoinState
    ) -> None:
        hints, _ = compute_spend_hints_and_additions(coin_spend)
        inner_puzzle_hash = hints[coin_state.coin.name()].hint
        assert inner_puzzle_hash
        dr = await self.wallet_state_manager.puzzle_store.get_derivation_record_for_puzzle_hash(inner_puzzle_hash)
        assert dr is not None
        hidden_puzzle_hash = get_vault_hidden_puzzle_with_index(dr.index).get_tree_hash()
        next_inner_puzzle = get_vault_inner_puzzle(
            self.vault_info.pubkey,
            self.wallet_state_manager.constants.GENESIS_CHALLENGE,
            hidden_puzzle_hash,
            self.vault_info.recovery_info.bls_pk,
            self.vault_info.recovery_info.timelock,
        )

        # get the parent state to create lineage proof
        wallet_node: Any = self.wallet_state_manager.wallet_node
        peer = wallet_node.get_full_node_peer()
        assert peer is not None
        parent_state = (await wallet_node.get_coin_state([coin_state.coin.parent_coin_info], peer))[0]
        parent_spend = await fetch_coin_spend(uint32(parent_state.spent_height), parent_state.coin, peer)
        parent_puzzle = parent_spend.puzzle_reveal.to_program()
        parent_inner_puzzle_hash = parent_puzzle.uncurry()[1].at("rf").get_tree_hash()
        lineage_proof = LineageProof(
            parent_state.coin.parent_coin_info, parent_inner_puzzle_hash, parent_state.coin.amount
        )
        new_vault_info = VaultInfo(
            coin_state.coin,
            self.vault_info.pubkey,
            hidden_puzzle_hash,
            next_inner_puzzle.get_tree_hash(),
            lineage_proof,
            self.vault_info.is_recoverable,
            self.vault_info.recovery_info,
        )

        await self.update_vault_store(new_vault_info, coin_spend)
        await self.save_info(new_vault_info)

    async def save_info(self, vault_info: VaultInfo) -> None:
        self._vault_info = vault_info

    async def update_vault_store(self, vault_info: VaultInfo, coin_spend: CoinSpend) -> None:
        custom_data = bytes(
            json.dumps(
                {
                    "vault_info": vault_info.to_json_dict(),
                }
            ),
            "utf-8",
        )
        await self.wallet_state_manager.singleton_store.add_spend(self.id(), coin_spend, custom_data=custom_data)
