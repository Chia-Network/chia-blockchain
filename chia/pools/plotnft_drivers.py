from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field, replace
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
    SINGLETON_MOD,
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
class SingletonStruct:
    launcher_id: bytes32
    singleton_mod: Program = field(default_factory=lambda: SINGLETON_MOD)
    singleton_launcher: Program = field(default_factory=lambda: SINGLETON_LAUNCHER)


@dataclass(kw_only=True, frozen=True)
class SelfCustody:
    member: BLSWithTaprootMember

    def puzzle_with_restrictions(self) -> PuzzleWithRestrictions:
        return PuzzleWithRestrictions(
            nonce=0, restrictions=[], puzzle=self.member, additional_memos=self.memos(nonce=0)
        )

    def memos(self, nonce: int) -> Program:
        return Program.to([self.member.synthetic_key])

    def puzzle(self, nonce: int) -> Program:
        return self.puzzle_with_restrictions().puzzle_reveal()

    def puzzle_hash(self, nonce: int) -> bytes32:
        return self.puzzle(nonce=nonce).get_tree_hash()  # TODO: optimize


@dataclass(kw_only=True, frozen=True)
class PlotNFTConfig:
    self_custody_pubkey: G1Element
    pool_puzzle_hash: bytes32 | None = None
    timelock: uint64 | None = None


@dataclass(kw_only=True, frozen=True)
class PoolingCustody:
    singleton_struct: SingletonStruct
    synthetic_pubkey: G1Element
    pool_puzzle_hash: bytes32
    timelock: uint64
    exiting: bool
    genesis_challenge: bytes32

    @property
    def reward_puzhash(self) -> bytes32:
        return RewardPuzzle(singleton_id=self.singleton_struct.launcher_id).puzzle_hash()

    @property
    def config(self) -> PlotNFTConfig:
        return PlotNFTConfig(
            self_custody_pubkey=self.synthetic_pubkey, pool_puzzle_hash=self.pool_puzzle_hash, timelock=self.timelock
        )

    @property
    def self_custody(self) -> SelfCustody:
        return SelfCustody(member=BLSWithTaprootMember(synthetic_key=self.synthetic_pubkey))

    def waiting_room_puzzle(self) -> Program:
        return dataclasses.replace(self, exiting=True).puzzle(nonce=0)

    def claim_pool_reward_dpuz(self) -> Program:
        return CLAIM_POOL_REWARDS_DELEGATED_PUZZLE.curry(
            self.genesis_challenge[:16],
            self.singleton_struct.singleton_mod.get_tree_hash(),  # TODO: optimize
            Program.to(
                (
                    self.singleton_struct.singleton_mod.get_tree_hash(),
                    (self.singleton_struct.launcher_id, self.singleton_struct.singleton_launcher.get_tree_hash()),
                )
            ).get_tree_hash(),  # TODO: optimize
            self.reward_puzhash,
            forward_to_pool_puzzle_hash_dpuz(self.pool_puzzle_hash).get_tree_hash(),
        )

    def claim_pool_reward_dpuz_and_solution(self, reward: PoolReward) -> DelegatedPuzzleAndSolution:
        return DelegatedPuzzleAndSolution(
            puzzle=self.claim_pool_reward_dpuz(),
            solution=Program.to([self.puzzle_hash(nonce=0), reward.height, reward.coin.amount]),
        )

    def user_restriction(self) -> ValidatorStackRestriction:
        return ValidatorStackRestriction(
            required_wrappers=[
                FixedCreateCoinDestinations(allowed_ph=self.waiting_room_puzzle().get_tree_hash()),
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
            puzzle=self.self_custody.member,
        )

    def user_proven_spend(self, premodified_dpuz: Program) -> dict[bytes32, ProvenSpend]:
        return {
            self.user_puzzle_with_restrictions().puzzle_hash(_top_level=False): ProvenSpend(
                puzzle_reveal=self.user_puzzle_with_restrictions().puzzle_reveal(_top_level=False),
                solution=self.user_puzzle_with_restrictions().solve(
                    member_validator_solutions=[],
                    dpuz_validator_solutions=[self.user_restriction().solve(premodified_dpuz)],
                    member_solution=self.self_custody.member.solve(),
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
            ),
            additional_memos=self.memos(nonce=0),
        )

    def memos(self, nonce: int) -> Program:
        return Program.to([self.self_custody.member.synthetic_key, self.pool_puzzle_hash, self.timelock])

    def puzzle(self, nonce: int) -> Program:
        return self.puzzle_with_restrictions().puzzle_reveal()

    def puzzle_hash(self, nonce: int) -> bytes32:
        return self.puzzle(nonce=nonce).get_tree_hash()  # TODO: optimize


@dataclass(kw_only=True, frozen=True)
class PlotNFTPuzzle:
    singleton_struct: SingletonStruct
    inner_custody: SelfCustody | PoolingCustody

    def __post_init__(self) -> None:
        if (
            isinstance(self.inner_custody, PoolingCustody)
            and self.inner_custody.singleton_struct != self.singleton_struct
        ):
            raise ValueError("Bad initialization of PlotNFTPuzzle, inner custody has different singleton information.")

    @property
    def bls_member(self) -> BLSWithTaprootMember:
        if isinstance(self.inner_custody, PoolingCustody):
            return self.inner_custody.self_custody.member
        else:
            return self.inner_custody.member

    def puzzle(self) -> Program:
        return puzzle_for_singleton(
            launcher_id=self.singleton_struct.launcher_id,
            inner_puz=self.inner_custody.puzzle(nonce=0),
            # TODO: optimize
            launcher_hash=self.singleton_struct.singleton_launcher.get_tree_hash(),
            singleton_mod=self.singleton_struct.singleton_mod,
            singleton_mod_hash=self.singleton_struct.singleton_mod.get_tree_hash(),
        )

    def puzzle_hash(self) -> bytes32:
        return self.puzzle().get_tree_hash()  # TODO: optimize

    def forward_pool_reward_inner_solution(self, reward: PoolReward) -> Program:
        assert isinstance(self.inner_custody, PoolingCustody)
        custody_pwr = self.inner_custody.puzzle_with_restrictions()
        assert isinstance(custody_pwr.puzzle, MofN)
        return custody_pwr.solve(
            member_validator_solutions=[],
            dpuz_validator_solutions=[],
            member_solution=custody_pwr.puzzle.solve(self.inner_custody.pool_proven_spend()),
            delegated_puzzle_and_solution=self.inner_custody.claim_pool_reward_dpuz_and_solution(reward),
        )

    def exit_to_from_waiting_room_inner_solution(
        self, delegated_puzzle_and_solution: DelegatedPuzzleAndSolution
    ) -> Program:
        assert isinstance(self.inner_custody, PoolingCustody)
        custody_pwr = self.inner_custody.puzzle_with_restrictions()
        assert isinstance(custody_pwr.puzzle, MofN)
        return custody_pwr.solve(
            member_validator_solutions=[],
            dpuz_validator_solutions=[],
            member_solution=custody_pwr.puzzle.solve(
                self.inner_custody.user_proven_spend(delegated_puzzle_and_solution.puzzle)
            ),
            delegated_puzzle_and_solution=self.inner_custody.user_restriction().modify_delegated_puzzle_and_solution(
                delegated_puzzle_and_solution, [Program.to([]), Program.to([])]
            ),
        )


@dataclass(kw_only=True, frozen=True)
class PlotNFT:
    coin: Coin
    singleton_lineage_proof: LineageProof
    puzzle: PlotNFTPuzzle
    singleton_mod: ClassVar[Program] = SINGLETON_MOD
    singleton_launcher: ClassVar[Program] = SINGLETON_LAUNCHER

    @property
    def config(self) -> PlotNFTConfig:
        if isinstance(self.puzzle.inner_custody, PoolingCustody):
            return self.puzzle.inner_custody.config
        else:
            assert self.puzzle.inner_custody.member.synthetic_key is not None
            return PlotNFTConfig(self_custody_pubkey=self.puzzle.inner_custody.member.synthetic_key)

    @classmethod
    def origin_coin_info(
        cls,
        origin_coins: list[Coin],
    ) -> tuple[Coin, Coin, SingletonStruct]:
        origin_coin = origin_coins[0]

        launcher_hash = cls.singleton_launcher.get_tree_hash()
        launcher_coin = Coin(origin_coin.name(), launcher_hash, uint64(1))
        launcher_id = launcher_coin.name()
        singleton_struct = SingletonStruct(
            singleton_mod=cls.singleton_mod, launcher_id=launcher_id, singleton_launcher=cls.singleton_launcher
        )

        return origin_coin, launcher_coin, singleton_struct

    @classmethod
    def launch(
        cls,
        *,
        origin_coins: list[Coin],
        custody: SelfCustody | PoolingCustody,
        fee: uint64 = uint64(0),
        extra_conditions: tuple[Condition, ...] = tuple(),
    ) -> tuple[list[Program], list[CoinSpend], Self]:
        mod_hash = cls.singleton_mod.get_tree_hash()
        launcher_hash = cls.singleton_launcher.get_tree_hash()
        origin_coin, launcher_coin, singleton_struct = cls.origin_coin_info(origin_coins)
        launcher_id = launcher_coin.name()

        plotnft_puzzle = PlotNFTPuzzle(singleton_struct=singleton_struct, inner_custody=custody)
        rev_puzzle = Program.to(
            (
                1,
                [
                    CreateCoin(
                        plotnft_puzzle.inner_custody.puzzle_hash(nonce=0),
                        uint64(1),
                        memo_blob=plotnft_puzzle.inner_custody.puzzle_with_restrictions().memo(),
                    ).to_program(),
                    CreateCoinAnnouncement(msg=b"").to_program(),
                ],
            )
        )
        full_rev_singleton_puzzle = puzzle_for_singleton(
            launcher_id,
            rev_puzzle,
            singleton_mod=cls.singleton_mod,
            launcher_hash=launcher_hash,
            singleton_mod_hash=mod_hash,
        )
        rev_coin = Coin(launcher_id, full_rev_singleton_puzzle.get_tree_hash(), uint64(1))
        rev_coin_id = rev_coin.name()
        launcher_solution = Program.to([full_rev_singleton_puzzle.get_tree_hash(), uint64(1), None])

        conditions = [
            CreateCoin(launcher_hash, uint64(1)),
            CreateCoin(origin_coin.puzzle_hash, uint64(sum(c.amount for c in origin_coins) - fee - 1)),
            ReserveFee(fee),
            AssertCoinAnnouncement(asserted_id=launcher_id, asserted_msg=launcher_solution.get_tree_hash()),
            AssertCoinAnnouncement(asserted_id=rev_coin_id, asserted_msg=b""),
            *extra_conditions,
        ]
        launcher_spend = make_spend(
            launcher_coin,
            cls.singleton_launcher,
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
                coin=Coin(rev_coin_id, plotnft_puzzle.puzzle_hash(), uint64(1)),
                singleton_lineage_proof=LineageProof(
                    parent_name=rev_coin.parent_coin_info,
                    inner_puzzle_hash=rev_puzzle.get_tree_hash(),
                    amount=rev_coin.amount,
                ),
                puzzle=plotnft_puzzle,
            ),
        )

    @classmethod
    def get_next_from_coin_spend(
        cls,
        *,
        coin_spend: CoinSpend,
        genesis_challenge: bytes32,
        pre_uncurry: UncurriedPuzzle | None = None,
        previous_pool_config: PlotNFTConfig | None = None,
    ) -> Self:
        if pre_uncurry is None:
            singleton = uncurry_puzzle(coin_spend.puzzle_reveal)
        else:
            singleton = pre_uncurry

        if singleton.mod != cls.singleton_mod:
            raise ValueError("Invalid singleton mod for next PlotNFT")
        if singleton.args.at("frr") != cls.singleton_launcher.get_tree_hash():  # TODO: optimize
            raise ValueError("Invalid singleton launcher for next PlotNFT")

        singleton_struct = SingletonStruct(
            singleton_mod=cls.singleton_mod,
            singleton_launcher=cls.singleton_launcher,
            launcher_id=bytes32(singleton.args.at("frf").as_atom()),
        )

        inner_puzzle = singleton.args.at("rf")
        inner_conditions = parse_conditions_non_consensus(
            run(inner_puzzle, Program.from_serialized(coin_spend.solution).at("rrf")).as_iter()
        )
        singleton_create_coin = next(condition for condition in inner_conditions if isinstance(condition, CreateCoin))
        config = None
        exiting = False
        if singleton_create_coin.puzzle_hash == inner_puzzle.get_tree_hash() and previous_pool_config is not None:
            config = previous_pool_config

        if config is None and previous_pool_config is not None:
            potential_self_custody = SelfCustody(
                member=BLSWithTaprootMember(
                    synthetic_key=previous_pool_config.self_custody_pubkey,
                )
            )
            if potential_self_custody.puzzle_hash(nonce=0) == singleton_create_coin.puzzle_hash:
                config = PlotNFTConfig(self_custody_pubkey=previous_pool_config.self_custody_pubkey)
            elif previous_pool_config.pool_puzzle_hash is not None:
                assert previous_pool_config.timelock is not None
                potential_exiting_config = replace(
                    PoolingCustody(
                        singleton_struct=singleton_struct,
                        synthetic_pubkey=previous_pool_config.self_custody_pubkey,
                        pool_puzzle_hash=previous_pool_config.pool_puzzle_hash,
                        timelock=previous_pool_config.timelock,
                        exiting=True,
                        genesis_challenge=genesis_challenge,
                    )
                )
                if potential_exiting_config.puzzle_hash(nonce=0) == singleton_create_coin.puzzle_hash:
                    config = previous_pool_config
                    exiting = True

        if config is None:
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

            config = PlotNFTConfig(self_custody_pubkey=pubkey, pool_puzzle_hash=pool_puzzle_hash, timelock=timelock)

        if config.pool_puzzle_hash is not None:
            assert config.timelock is not None
            custody: SelfCustody | PoolingCustody = PoolingCustody(
                singleton_struct=singleton_struct,
                synthetic_pubkey=config.self_custody_pubkey,
                pool_puzzle_hash=config.pool_puzzle_hash,
                timelock=config.timelock,
                exiting=exiting,
                genesis_challenge=genesis_challenge,
            )
        else:
            custody = SelfCustody(
                member=BLSWithTaprootMember(
                    synthetic_key=config.self_custody_pubkey,
                )
            )

        return cls(
            coin=Coin(
                coin_spend.coin.name(),
                puzzle_for_singleton(
                    launcher_id=singleton_struct.launcher_id,
                    inner_puz=custody.puzzle(nonce=0),
                    # TODO: optimize
                    singleton_mod=cls.singleton_mod,
                    launcher_hash=cls.singleton_launcher.get_tree_hash(),
                    singleton_mod_hash=cls.singleton_mod.get_tree_hash(),
                ).get_tree_hash(),
                coin_spend.coin.amount,
            ),
            singleton_lineage_proof=LineageProof(
                parent_name=coin_spend.coin.parent_coin_info,
                inner_puzzle_hash=inner_puzzle.get_tree_hash(),
                amount=coin_spend.coin.amount,
            ),
            puzzle=PlotNFTPuzzle(
                singleton_struct=singleton_struct,
                inner_custody=custody,
            ),
        )

    def singleton_action_spend(self, inner_solution: Program) -> CoinSpend:
        return make_spend(
            coin=self.coin,
            puzzle_reveal=puzzle_for_singleton(
                launcher_id=self.puzzle.singleton_struct.launcher_id,
                inner_puz=self.puzzle.inner_custody.puzzle(nonce=0),  # TODO: optimize
                singleton_mod=self.puzzle.singleton_struct.singleton_mod,
                singleton_mod_hash=self.puzzle.singleton_struct.singleton_mod.get_tree_hash(),  # TODO: optimize
                launcher_hash=self.puzzle.singleton_struct.singleton_launcher.get_tree_hash(),  # TODO: optimize
            ),
            solution=solution_for_singleton(
                lineage_proof=self.singleton_lineage_proof,
                amount=self.coin.amount,
                inner_solution=inner_solution,
            ),
        )

    def forward_pool_reward(self, reward: PoolReward) -> list[CoinSpend]:
        if not isinstance(self.puzzle.inner_custody, PoolingCustody):
            raise ValueError("Cannot forward pool reward while self pooling. Try `claim_pool_reward`")
        return [
            self.singleton_action_spend(inner_solution=self.puzzle.forward_pool_reward_inner_solution(reward)),
            make_spend(
                coin=reward.coin,
                puzzle_reveal=reward.puzzle.puzzle(),
                solution=reward.puzzle.solve(
                    self.puzzle.inner_custody.puzzle_hash(nonce=0),
                    delegated_puzzle_and_solution=DelegatedPuzzleAndSolution(
                        puzzle=forward_to_pool_puzzle_hash_dpuz(self.puzzle.inner_custody.pool_puzzle_hash),
                        solution=Program.to([reward.coin.amount]),
                    ),
                ),
            ),
        ]

    def exit_to_waiting_room(self, delegated_puzzle_and_solution: DelegatedPuzzleAndSolution) -> list[CoinSpend]:
        if not isinstance(self.puzzle.inner_custody, PoolingCustody):
            raise ValueError("Cannot exit to waiting room while self pooling.")
        if self.puzzle.inner_custody.exiting:
            raise ValueError("Already exiting to waiting room, cannot exit again")
        return [
            self.singleton_action_spend(
                inner_solution=self.puzzle.exit_to_from_waiting_room_inner_solution(delegated_puzzle_and_solution)
            )
        ]

    def exit_waiting_room(self, delegated_puzzle_and_solution: DelegatedPuzzleAndSolution) -> list[CoinSpend]:
        if not isinstance(self.puzzle.inner_custody, PoolingCustody):
            raise ValueError("Cannot exit waiting room while self pooling.")
        if not self.puzzle.inner_custody.exiting:
            raise ValueError("Cannot exit waiting room while not in it")
        return [
            self.singleton_action_spend(
                inner_solution=self.puzzle.exit_to_from_waiting_room_inner_solution(delegated_puzzle_and_solution)
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
                        CreateCoin(
                            puzzle_hash=self.puzzle.inner_custody.puzzle_hash(nonce=0), amount=self.coin.amount
                        ).to_program(),
                        SendMessage(
                            msg=reward_delegated_puzzle_and_solution.puzzle.get_tree_hash(),
                            sender=MessageParticipant(puzzle_hash_committed=self.puzzle.puzzle_hash()),
                            receiver=MessageParticipant(coin_id_committed=reward.coin.name()),
                        ).to_program(),
                    ],
                )
            ),
            solution=Program.to([]),
        )
        return dpuz_and_solution.puzzle.get_tree_hash(), [
            self.singleton_action_spend(
                inner_solution=self.puzzle.inner_custody.puzzle_with_restrictions().solve(
                    member_validator_solutions=[],
                    dpuz_validator_solutions=[],
                    member_solution=self.puzzle.bls_member.solve(),
                    delegated_puzzle_and_solution=dpuz_and_solution,
                )
            ),
            make_spend(
                coin=reward.coin,
                puzzle_reveal=reward.puzzle.puzzle(),
                solution=reward.puzzle.solve(
                    self.puzzle.inner_custody.puzzle_hash(nonce=0),
                    delegated_puzzle_and_solution=reward_delegated_puzzle_and_solution,
                ),
            ),
        ]

    def join_pool(self, pooling_custody: PoolingCustody) -> tuple[bytes32, list[CoinSpend]]:
        dpuz_and_solution = DelegatedPuzzleAndSolution(
            puzzle=Program.to(
                (
                    1,
                    [
                        CreateCoin(
                            pooling_custody.puzzle_hash(nonce=0),
                            amount=self.coin.amount,
                            memo_blob=pooling_custody.puzzle_with_restrictions().memo(),
                        ).to_program()
                    ],
                )
            ),
            solution=Program.to([]),
        )
        return dpuz_and_solution.puzzle.get_tree_hash(), [
            self.singleton_action_spend(
                inner_solution=self.puzzle.inner_custody.puzzle_with_restrictions().solve(
                    member_validator_solutions=[],
                    dpuz_validator_solutions=[],
                    member_solution=self.puzzle.bls_member.solve(),
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
