from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field, replace
from functools import cached_property
from typing import ClassVar, Self

from chia_rs import G1Element
from chia_rs.chia_rs import Coin, CoinSpend
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32, uint64

from chia.types.blockchain_format.program import Program, run
from chia.types.coin_spend import make_spend
from chia.wallet.conditions import (
    AssertCoinAnnouncement,
    Condition,
    CreateCoin,
    CreateCoinAnnouncement,
    MessageParticipant,
    ReserveFee,
    SendMessage,
    parse_conditions_non_consensus,
)
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.puzzles.custody.custody_architecture import (
    DelegatedPuzzleAndSolution,
    MofN,
    ProvenSpend,
    PuzzleWithRestrictions,
)
from chia.wallet.puzzles.custody.member_puzzles import BLSWithTaprootMember, FixedPuzzleMember, SingletonMember
from chia.wallet.puzzles.custody.restriction_utilities import ValidatorStackRestriction
from chia.wallet.puzzles.custody.restrictions import FixedCreateCoinDestinations, Timelock
from chia.wallet.puzzles.load_clvm import load_clvm_maybe_recompile
from chia.wallet.puzzles.singleton_top_layer_v1_1 import (
    SINGLETON_LAUNCHER,
    SINGLETON_LAUNCHER_HASH,
    SINGLETON_MOD,
    SINGLETON_MOD_HASH,
    puzzle_for_singleton,
    solution_for_singleton,
)
from chia.wallet.uncurried_puzzle import UncurriedPuzzle, uncurry_puzzle

CLAIM_POOL_REWARDS_DELEGATED_PUZZLE = load_clvm_maybe_recompile(
    "claim_pool_rewards_dpuz.clsp", package_or_requirement="chia.pools"
)
SEND_MESSAGE_BANNED = load_clvm_maybe_recompile("send_message_banned.clsp", package_or_requirement="chia.pools")


@dataclass(kw_only=True, frozen=True)
class SendMessageBanned:
    @property
    def member_not_dpuz(self) -> bool:
        return False

    def memo(self, nonce: int) -> Program:
        return Program.to(None)

    def puzzle(self, nonce: int) -> Program:
        return SEND_MESSAGE_BANNED

    def puzzle_hash(self, nonce: int) -> bytes32:
        return self.puzzle(nonce).get_tree_hash()  # TODO: optimize


def forward_to_pool_puzzle_hash_dpuz(pool_puzzle_hash: bytes32) -> Program:
    # TODO: optimize and examine
    # TODO: Figure out standard memos
    # (mod (REWARD_HASH REWARD_REST reward_amount)
    #   (list (list 73 reward_amount) (c 51 (c REWARD_HASH (c reward_amount REWARD_REST)))
    # )
    return Program.fromhex(
        "ff04ffff04ffff0149ffff04ff0bff808080ffff04ffff04ffff0133ffff04ff02ffff04ff0bff05808080ff808080"
    ).curry(pool_puzzle_hash, None)


@dataclass(kw_only=True, frozen=True)
class SingletonPuzzles:
    singleton_mod: Program = field(default_factory=lambda: SINGLETON_MOD)
    singleton_mod_hash_pre_computed: bytes32 | None = SINGLETON_MOD_HASH
    singleton_launcher: Program = field(default_factory=lambda: SINGLETON_LAUNCHER)
    singleton_launcher_hash_pre_computed: bytes32 | None = SINGLETON_LAUNCHER_HASH

    @cached_property
    def singleton_mod_hash(self) -> bytes32:
        if self.singleton_mod_hash_pre_computed is not None:
            return self.singleton_mod_hash_pre_computed
        else:
            return self.singleton_mod.get_tree_hash()

    @cached_property
    def singleton_launcher_hash(self) -> bytes32:
        if self.singleton_launcher_hash_pre_computed is not None:
            return self.singleton_launcher_hash_pre_computed
        else:
            return self.singleton_launcher.get_tree_hash()


@dataclass(kw_only=True, frozen=True)
class SingletonStruct:
    launcher_id: bytes32
    singleton_puzzles: SingletonPuzzles = SingletonPuzzles()

    def to_program(self) -> Program:
        return Program.to(
            (
                self.singleton_puzzles.singleton_mod_hash,
                (self.launcher_id, self.singleton_puzzles.singleton_launcher_hash),
            )
        )


@dataclass(kw_only=True, frozen=True)
class PoolConfig:
    pool_puzzle_hash: bytes32 | None = None
    timelock: uint64 | None = None

    def __post_init__(self) -> None:
        if (self.pool_puzzle_hash is None and self.timelock is not None) or (
            self.pool_puzzle_hash is not None and self.timelock is None
        ):
            raise ValueError("pool_puzzle_hash and timelock must be both None or both not None")


@dataclass(kw_only=True, frozen=True)
class UserConfig:
    synthetic_pubkey: G1Element


@dataclass(kw_only=True, frozen=True)
class PlotNFTPuzzle:
    launcher_id: bytes32
    genesis_challenge: bytes32
    user_config: UserConfig
    exiting: bool
    pool_config: PoolConfig = PoolConfig()
    singleton_puzzles: ClassVar[SingletonPuzzles] = SingletonPuzzles()

    def __post_init__(self) -> None:
        if self.pool_config == PoolConfig() and self.exiting:
            raise ValueError("Cannot initialize a PlotNFTPuzzle with an empty pool config and exiting=True")

    @property
    def singleton_struct(self) -> SingletonStruct:
        return SingletonStruct(launcher_id=self.launcher_id, singleton_puzzles=self.singleton_puzzles)

    @property
    def pooling(self) -> bool:
        return self.pool_config != PoolConfig()

    @property
    def pool_puzzle_hash(self) -> bytes32:
        if self.pool_config.pool_puzzle_hash is None:
            raise ValueError("Plot NFT is not pooling, cannot retrieve pool puzzle hash")
        return self.pool_config.pool_puzzle_hash

    @property
    def timelock(self) -> uint64:
        if self.pool_config.timelock is None:
            raise ValueError("Plot NFT is not pooling, cannot retrieve timelock")
        return self.pool_config.timelock

    @property
    def bls_member(self) -> BLSWithTaprootMember:
        return BLSWithTaprootMember(synthetic_key=self.user_config.synthetic_pubkey)

    @property
    def reward_puzhash(self) -> bytes32:
        return RewardPuzzle(singleton_id=self.launcher_id).puzzle_hash()

    def waiting_room_puzzle(self) -> Self:
        return dataclasses.replace(self, exiting=True)

    def claim_pool_reward_dpuz(self) -> Program:
        return CLAIM_POOL_REWARDS_DELEGATED_PUZZLE.curry(
            self.genesis_challenge[:16],
            self.singleton_struct.singleton_puzzles.singleton_mod_hash,
            self.singleton_struct.to_program().get_tree_hash(),  # TODO: optimize
            self.reward_puzhash,
            forward_to_pool_puzzle_hash_dpuz(self.pool_puzzle_hash).get_tree_hash(),
        )

    def claim_pool_reward_dpuz_and_solution(self, reward: PoolReward) -> DelegatedPuzzleAndSolution:
        return DelegatedPuzzleAndSolution(
            puzzle=self.claim_pool_reward_dpuz(),
            solution=Program.to([self.inner_puzzle_hash(), reward.height, reward.coin.amount]),
        )

    def user_restriction(self) -> ValidatorStackRestriction:
        return ValidatorStackRestriction(
            required_wrappers=[
                FixedCreateCoinDestinations(allowed_ph=self.waiting_room_puzzle().inner_puzzle().get_tree_hash()),
                SendMessageBanned(),
            ]
            if not self.exiting
            else [Timelock(self.timelock), SendMessageBanned()]
        )

    def modify_delegated_puzzle_and_solution(
        self, delegated_puzzle_and_solution: DelegatedPuzzleAndSolution
    ) -> DelegatedPuzzleAndSolution:
        return self.user_restriction().modify_delegated_puzzle_and_solution(
            delegated_puzzle_and_solution, [Program.to(None), Program.to(None)]
        )

    def user_puzzle_with_restrictions(self) -> PuzzleWithRestrictions:
        return PuzzleWithRestrictions(
            nonce=0,
            restrictions=[self.user_restriction()],
            puzzle=self.bls_member,
        )

    def user_proven_spend(self, premodified_dpuz: Program) -> dict[bytes32, ProvenSpend]:
        return {
            self.user_puzzle_with_restrictions().puzzle_hash(_top_level=False): ProvenSpend(
                puzzle_reveal=self.user_puzzle_with_restrictions().puzzle_reveal(_top_level=False),
                solution=self.user_puzzle_with_restrictions().solve(
                    member_validator_solutions=[],
                    dpuz_validator_solutions=[self.user_restriction().solve(premodified_dpuz)],
                    member_solution=self.bls_member.solve(),
                ),
            )
        }

    def fixed_puzzle_member(self) -> FixedPuzzleMember:
        # TODO: optimize
        return FixedPuzzleMember(fixed_puzzle_hash=self.claim_pool_reward_dpuz().get_tree_hash())

    def pool_puzzle_with_restrictions(self) -> PuzzleWithRestrictions:
        return PuzzleWithRestrictions(
            nonce=0,
            restrictions=[],
            puzzle=self.fixed_puzzle_member(),
        )

    def pool_proven_spend(self) -> dict[bytes32, ProvenSpend]:
        return {
            # TODO: optimize
            self.pool_puzzle_with_restrictions().puzzle_hash(_top_level=False): ProvenSpend(
                puzzle_reveal=self.pool_puzzle_with_restrictions().puzzle_reveal(_top_level=False),
                solution=self.pool_puzzle_with_restrictions().solve(
                    member_validator_solutions=[],
                    dpuz_validator_solutions=[],
                    member_solution=self.fixed_puzzle_member().solve(),
                ),
            )
        }

    def puzzle_with_restrictions(self) -> PuzzleWithRestrictions:
        return PuzzleWithRestrictions(
            nonce=0,
            restrictions=[],
            puzzle=MofN(
                m=1,
                members=[
                    self.user_puzzle_with_restrictions(),
                    self.pool_puzzle_with_restrictions(),
                ],
            )
            if self.pooling
            else self.bls_member,
            additional_memos=self.additional_memos(),
        )

    def memo(self) -> Program:
        return self.puzzle_with_restrictions().memo()

    def additional_memos(self) -> Program:
        if self.pooling:
            return Program.to([self.bls_member.synthetic_key, self.pool_puzzle_hash, self.timelock])
        else:
            return Program.to([self.bls_member.synthetic_key])

    def inner_puzzle(self) -> Program:
        return self.puzzle_with_restrictions().puzzle_reveal()

    def inner_puzzle_hash(self) -> bytes32:
        return self.inner_puzzle().get_tree_hash()  # TODO: optimize

    def puzzle(self, nonce: int) -> Program:
        return puzzle_for_singleton(
            launcher_id=self.singleton_struct.launcher_id,
            launcher_hash=self.singleton_struct.singleton_puzzles.singleton_launcher_hash,
            singleton_mod=self.singleton_struct.singleton_puzzles.singleton_mod,
            singleton_mod_hash=self.singleton_struct.singleton_puzzles.singleton_mod_hash,
            inner_puz=self.puzzle_with_restrictions().puzzle_reveal(),
        )

    def puzzle_hash(self, nonce: int) -> bytes32:
        return self.puzzle(nonce).get_tree_hash()  # TODO: optimize

    def forward_pool_reward_inner_solution(self, reward: PoolReward) -> Program:
        custody_pwr = self.puzzle_with_restrictions()
        assert isinstance(custody_pwr.puzzle, MofN)
        return custody_pwr.solve(
            member_validator_solutions=[],
            dpuz_validator_solutions=[],
            member_solution=custody_pwr.puzzle.solve(self.pool_proven_spend()),
            delegated_puzzle_and_solution=self.claim_pool_reward_dpuz_and_solution(reward),
        )

    def exit_to_from_waiting_room_inner_solution(
        self, delegated_puzzle_and_solution: DelegatedPuzzleAndSolution
    ) -> Program:
        custody_pwr = self.puzzle_with_restrictions()
        assert isinstance(custody_pwr.puzzle, MofN)
        return custody_pwr.solve(
            member_validator_solutions=[],
            dpuz_validator_solutions=[],
            member_solution=custody_pwr.puzzle.solve(self.user_proven_spend(delegated_puzzle_and_solution.puzzle)),
            delegated_puzzle_and_solution=self.user_restriction().modify_delegated_puzzle_and_solution(
                delegated_puzzle_and_solution, [Program.to([]), Program.to([])]
            ),
        )


@dataclass(kw_only=True, frozen=True)
class PlotNFT(PlotNFTPuzzle):
    coin: Coin
    singleton_lineage_proof: LineageProof

    @classmethod
    def launch(
        cls,
        *,
        origin_coins: list[Coin],
        user_config: UserConfig,
        genesis_challenge: bytes32,
        pool_config: PoolConfig = PoolConfig(),
        exiting: bool = True,
        fee: uint64 = uint64(0),
        extra_conditions: tuple[Condition, ...] = tuple(),
    ) -> tuple[list[Program], list[CoinSpend], Self]:
        origin_coin = origin_coins[0]
        launcher_coin = Coin(origin_coin.name(), cls.singleton_puzzles.singleton_launcher_hash, uint64(1))
        launcher_id = launcher_coin.name()

        plotnft_puzzle = PlotNFTPuzzle(
            launcher_id=launcher_id,
            user_config=user_config,
            pool_config=pool_config,
            exiting=exiting,
            genesis_challenge=genesis_challenge,
        )
        rev_puzzle = Program.to(
            (
                1,
                [
                    CreateCoin(
                        plotnft_puzzle.inner_puzzle_hash(),
                        uint64(1),
                        memo_blob=plotnft_puzzle.puzzle_with_restrictions().memo(),
                    ).to_program(),
                    CreateCoinAnnouncement(msg=b"").to_program(),
                ],
            )
        )
        full_rev_singleton_puzzle = puzzle_for_singleton(
            launcher_id,
            rev_puzzle,
            singleton_mod=cls.singleton_puzzles.singleton_mod,
            launcher_hash=cls.singleton_puzzles.singleton_launcher_hash,
            singleton_mod_hash=cls.singleton_puzzles.singleton_mod_hash,
        )
        rev_coin = Coin(launcher_id, full_rev_singleton_puzzle.get_tree_hash(), uint64(1))
        rev_coin_id = rev_coin.name()
        launcher_solution = Program.to([full_rev_singleton_puzzle.get_tree_hash(), uint64(1), None])

        conditions = [
            CreateCoin(cls.singleton_puzzles.singleton_launcher_hash, uint64(1)),
            CreateCoin(origin_coin.puzzle_hash, uint64(sum(c.amount for c in origin_coins) - fee - 1)),
            ReserveFee(fee),
            AssertCoinAnnouncement(asserted_id=launcher_id, asserted_msg=launcher_solution.get_tree_hash()),
            AssertCoinAnnouncement(asserted_id=rev_coin_id, asserted_msg=b""),
            *extra_conditions,
        ]
        launcher_spend = make_spend(
            launcher_coin,
            cls.singleton_puzzles.singleton_launcher,
            launcher_solution,
        )
        rev_spend = make_spend(
            rev_coin,
            full_rev_singleton_puzzle,
            solution_for_singleton(
                LineageProof(parent_name=launcher_coin.parent_coin_info, amount=launcher_coin.amount),
                uint64(1),
                Program.to(None),
            ),
        )
        return (
            [condition.to_program() for condition in conditions],
            [launcher_spend, rev_spend],
            cls(
                coin=Coin(rev_coin_id, plotnft_puzzle.puzzle_hash(nonce=0), uint64(1)),
                singleton_lineage_proof=LineageProof(
                    parent_name=rev_coin.parent_coin_info,
                    inner_puzzle_hash=rev_puzzle.get_tree_hash(),
                    amount=rev_coin.amount,
                ),
                launcher_id=launcher_id,
                user_config=user_config,
                pool_config=pool_config,
                exiting=exiting,
                genesis_challenge=genesis_challenge,
            ),
        )

    @classmethod
    def get_next_from_coin_spend(
        cls,
        *,
        coin_spend: CoinSpend,
        genesis_challenge: bytes32,
        pre_uncurry: UncurriedPuzzle | None = None,
        previous_plotnft_puzzle: PlotNFTPuzzle | None = None,
    ) -> Self:
        if pre_uncurry is None:
            singleton = uncurry_puzzle(coin_spend.puzzle_reveal)
        else:
            singleton = pre_uncurry

        if singleton.mod != cls.singleton_puzzles.singleton_mod:
            raise ValueError("Invalid singleton mod for next PlotNFT")
        if singleton.args.at("frr") != cls.singleton_puzzles.singleton_launcher_hash:
            raise ValueError("Invalid singleton launcher for next PlotNFT")

        launcher_id = bytes32(singleton.args.at("frf").as_atom())

        inner_puzzle = singleton.args.at("rf")
        inner_conditions = parse_conditions_non_consensus(
            run(inner_puzzle, Program.from_serialized(coin_spend.solution).at("rrf")).as_iter()
        )
        singleton_create_coin = next(condition for condition in inner_conditions if isinstance(condition, CreateCoin))
        plotnft_puzzle = None
        if singleton_create_coin.puzzle_hash == inner_puzzle.get_tree_hash() and previous_plotnft_puzzle is not None:
            plotnft_puzzle = previous_plotnft_puzzle

        if plotnft_puzzle is None and previous_plotnft_puzzle is not None:
            if (
                replace(previous_plotnft_puzzle, pool_config=PoolConfig(), exiting=False).inner_puzzle_hash()
                == singleton_create_coin.puzzle_hash
            ):
                plotnft_puzzle = replace(previous_plotnft_puzzle, pool_config=PoolConfig(), exiting=False)
            elif (
                replace(previous_plotnft_puzzle, exiting=True).inner_puzzle_hash() == singleton_create_coin.puzzle_hash
            ):
                plotnft_puzzle = replace(previous_plotnft_puzzle, exiting=True)

        if plotnft_puzzle is None:
            if singleton_create_coin.memo_blob is None:
                raise ValueError("Invalid memoization of PlotNFT")
            unknown_inner_puzzle = PuzzleWithRestrictions.from_memo(singleton_create_coin.memo_blob)
            assert unknown_inner_puzzle.additional_memos is not None
            pubkey = G1Element.from_bytes(unknown_inner_puzzle.additional_memos.at("f").as_atom())
            if isinstance(unknown_inner_puzzle.puzzle, MofN):
                pool_puzzle_hash = bytes32(unknown_inner_puzzle.additional_memos.at("rf").as_atom())
                timelock = uint64(unknown_inner_puzzle.additional_memos.at("rrf").as_int())
                exiting = (
                    ValidatorStackRestriction(required_wrappers=[Timelock(timelock), SendMessageBanned()]).puzzle_hash(
                        nonce=0
                    )
                    in unknown_inner_puzzle.unknown_puzzles
                )
            else:
                pool_puzzle_hash = None
                timelock = None
                exiting = False

            plotnft_puzzle = PlotNFTPuzzle(
                launcher_id=launcher_id,
                user_config=UserConfig(synthetic_pubkey=pubkey),
                pool_config=PoolConfig(pool_puzzle_hash=pool_puzzle_hash, timelock=timelock),
                exiting=exiting,
                genesis_challenge=genesis_challenge,
            )

        return cls(
            coin=Coin(
                coin_spend.coin.name(),
                plotnft_puzzle.puzzle(nonce=0).get_tree_hash(),
                coin_spend.coin.amount,
            ),
            singleton_lineage_proof=LineageProof(
                parent_name=coin_spend.coin.parent_coin_info,
                inner_puzzle_hash=inner_puzzle.get_tree_hash(),
                amount=coin_spend.coin.amount,
            ),
            launcher_id=launcher_id,
            user_config=plotnft_puzzle.user_config,
            pool_config=plotnft_puzzle.pool_config,
            exiting=plotnft_puzzle.exiting,
            genesis_challenge=genesis_challenge,
        )

    def singleton_action_spend(self, inner_solution: Program) -> CoinSpend:
        return make_spend(
            coin=self.coin,
            puzzle_reveal=puzzle_for_singleton(
                launcher_id=self.singleton_struct.launcher_id,
                inner_puz=self.inner_puzzle(),  # TODO: optimize
                singleton_mod=self.singleton_struct.singleton_puzzles.singleton_mod,
                singleton_mod_hash=self.singleton_struct.singleton_puzzles.singleton_mod_hash,
                launcher_hash=self.singleton_struct.singleton_puzzles.singleton_launcher_hash,
            ),
            solution=solution_for_singleton(
                lineage_proof=self.singleton_lineage_proof,
                amount=self.coin.amount,
                inner_solution=inner_solution,
            ),
        )

    def forward_pool_reward(self, reward: PoolReward) -> list[CoinSpend]:
        if not self.pooling:
            raise ValueError("Cannot forward pool reward while self pooling. Try `claim_pool_reward`")
        return [
            self.singleton_action_spend(inner_solution=self.forward_pool_reward_inner_solution(reward)),
            make_spend(
                coin=reward.coin,
                puzzle_reveal=reward.puzzle.puzzle(),
                solution=reward.puzzle.solve(
                    self.inner_puzzle_hash(),
                    delegated_puzzle_and_solution=DelegatedPuzzleAndSolution(
                        puzzle=forward_to_pool_puzzle_hash_dpuz(self.pool_puzzle_hash),
                        solution=Program.to([reward.coin.amount]),
                    ),
                ),
            ),
        ]

    def exit_to_waiting_room(self, delegated_puzzle_and_solution: DelegatedPuzzleAndSolution) -> list[CoinSpend]:
        if not self.pooling:
            raise ValueError("Cannot exit to waiting room while self pooling.")
        if self.exiting:
            raise ValueError("Already exiting to waiting room, cannot exit again")
        return [
            self.singleton_action_spend(
                inner_solution=self.exit_to_from_waiting_room_inner_solution(delegated_puzzle_and_solution)
            )
        ]

    def exit_waiting_room(self, delegated_puzzle_and_solution: DelegatedPuzzleAndSolution) -> list[CoinSpend]:
        if not self.pooling:
            raise ValueError("Cannot exit waiting room while self pooling.")
        if not self.exiting:
            raise ValueError("Cannot exit waiting room while not in it")
        return [
            self.singleton_action_spend(
                inner_solution=self.exit_to_from_waiting_room_inner_solution(delegated_puzzle_and_solution)
            )
        ]

    def claim_pool_reward(
        self, reward: PoolReward, reward_delegated_puzzle_and_solution: DelegatedPuzzleAndSolution
    ) -> tuple[bytes32, list[CoinSpend]]:
        dpuz_and_solution = DelegatedPuzzleAndSolution(
            puzzle=Program.to(
                (
                    1,
                    [
                        CreateCoin(puzzle_hash=self.inner_puzzle_hash(), amount=self.coin.amount).to_program(),
                        SendMessage(
                            msg=reward_delegated_puzzle_and_solution.puzzle.get_tree_hash(),
                            sender=MessageParticipant(puzzle_hash_committed=self.puzzle_hash(nonce=0)),
                            receiver=MessageParticipant(coin_id_committed=reward.coin.name()),
                        ).to_program(),
                    ],
                )
            ),
            solution=Program.to([]),
        )
        return dpuz_and_solution.puzzle.get_tree_hash(), [
            self.singleton_action_spend(
                inner_solution=self.puzzle_with_restrictions().solve(
                    member_validator_solutions=[],
                    dpuz_validator_solutions=[],
                    member_solution=self.bls_member.solve(),
                    delegated_puzzle_and_solution=dpuz_and_solution,
                )
            ),
            make_spend(
                coin=reward.coin,
                puzzle_reveal=reward.puzzle.puzzle(),
                solution=reward.puzzle.solve(
                    self.inner_puzzle_hash(),
                    delegated_puzzle_and_solution=reward_delegated_puzzle_and_solution,
                ),
            ),
        ]

    def join_pool(self, user_config: UserConfig, pool_config: PoolConfig) -> tuple[bytes32, list[CoinSpend]]:
        plotnft_puzzle = PlotNFTPuzzle(
            launcher_id=self.launcher_id,
            user_config=user_config,
            pool_config=pool_config,
            exiting=False,
            genesis_challenge=self.genesis_challenge,
        )

        dpuz_and_solution = DelegatedPuzzleAndSolution(
            puzzle=Program.to(
                (
                    1,
                    [
                        CreateCoin(
                            plotnft_puzzle.inner_puzzle_hash(),
                            amount=self.coin.amount,
                            memo_blob=plotnft_puzzle.memo(),
                        ).to_program()
                    ],
                )
            ),
            solution=Program.to([]),
        )
        return dpuz_and_solution.puzzle.get_tree_hash(), [
            self.singleton_action_spend(
                inner_solution=self.puzzle_with_restrictions().solve(
                    member_validator_solutions=[],
                    dpuz_validator_solutions=[],
                    member_solution=self.bls_member.solve(),
                    delegated_puzzle_and_solution=dpuz_and_solution,
                )
            )
        ]


@dataclass(kw_only=True, frozen=True)
class RewardPuzzle:
    singleton_id: bytes32

    @property
    def singleton_member(self) -> SingletonMember:
        return SingletonMember(singleton_id=self.singleton_id)

    def puzzle_with_restrictions(self) -> PuzzleWithRestrictions:
        return PuzzleWithRestrictions(nonce=0, restrictions=[], puzzle=self.singleton_member)

    def puzzle(self) -> Program:
        return self.puzzle_with_restrictions().puzzle_reveal()

    def puzzle_hash(self) -> bytes32:
        return self.puzzle().get_tree_hash()  # TODO: optimize

    def solve(
        self, singleton_inner_puzzle_hash: bytes32, delegated_puzzle_and_solution: DelegatedPuzzleAndSolution
    ) -> Program:
        return self.puzzle_with_restrictions().solve(
            [],
            [],
            self.singleton_member.solve(singleton_inner_puzzle_hash),
            delegated_puzzle_and_solution,
        )


@dataclass(kw_only=True, frozen=True)
class PoolReward:
    coin: Coin
    height: uint32
    puzzle: RewardPuzzle
