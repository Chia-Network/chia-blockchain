# flake8: noqa

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint8, uint16, uint32, uint64, uint128
from chia.types.blockchain_format.proof_of_space import ProofOfSpace
from chia.types.blockchain_format.pool_target import PoolTarget
from chia.types.coin_spend import CoinSpend
from chia.types.blockchain_format.coin import Coin
from chia.types.spend_bundle import SpendBundle
from chia.types.blockchain_format.program import Program, SerializedProgram
from chia.types.blockchain_format.sub_epoch_summary import SubEpochSummary
from chia.types.weight_proof import WeightProof, SubEpochData, SubEpochChallengeSegment, SubSlotData, RecentChainData
from chia.types.blockchain_format.vdf import VDFInfo, VDFProof
from chia.types.blockchain_format.classgroup import ClassgroupElement
from blspy import G1Element, G2Element
from chia.types.header_block import HeaderBlock
from chia.types.full_block import FullBlock
from chia.types.unfinished_block import UnfinishedBlock
from chia.types.blockchain_format.slots import (
    ChallengeChainSubSlot,
    InfusedChallengeChainSubSlot,
    RewardChainSubSlot,
    SubSlotProofs,
)
from chia.types.end_of_slot_bundle import EndOfSubSlotBundle
from chia.types.peer_info import TimestampedPeerInfo
from chia.types.blockchain_format.reward_chain_block import RewardChainBlock
from chia.types.blockchain_format.foliage import Foliage, FoliageTransactionBlock, FoliageBlockData, TransactionsInfo

from chia.protocols import (
    farmer_protocol,
    full_node_protocol,
    harvester_protocol,
    introducer_protocol,
    pool_protocol,
    timelord_protocol,
    wallet_protocol,
)

### FARMER PROTOCOL
new_signage_point = farmer_protocol.NewSignagePoint(
    bytes32([0] * 16 + [1] * 16),
    bytes32(b"a" * 16 + b"b" * 16),
    bytes32([0] * 32),
    uint64(123123),
    uint64(2 ** 16),
    uint8(15),
)

proof_of_space = ProofOfSpace(
    bytes32(bytes.fromhex("f0613f3b6b8258d6f62c6b13e53dd45d3eaf0abe74430f9a00de442310b8e499")),
    G1Element(
        bytes.fromhex(
            "a04c6b5ac7dfb935f6feecfdd72348ccf1d4be4fe7e26acf271ea3b7d308da61e0a308f7a62495328a81f5147b66634c"
        ),
    ),
    None,
    G1Element(
        bytes.fromhex(
            "b6449c2c68df97c19e884427e42ee7350982d4020571ead08732615ff39bd216bfd630b6460784982bec98b49fea79d0"
        ),
    ),
    uint8(22),
    bytes.fromhex(
        "a67188ae0c02c49b0e821a9773033a3fbd338030c383080dbb8b1d63f07af427d8075e59d911f85ea562fd967823588f9a405a4464fdf5dc0866ee15bebd6b94cb147e28aa9cf96da930611486b779737ed721ea376b9939ba05357141223d75d21b21f310ec32d85ed3b98cf301494ea91b8501138481f3bfa1c384fd998b1fdd2855ac6f0c8554c520fb0bfa3663f238124035e14682bc11eaf7c372b6af4ed7f59a406810c71711906f8c91f94b1f",
    ),
)

pool_target = PoolTarget(bytes.fromhex("d23da14695a188ae5708dd152263c4db883eb27edeb936178d4d988b8f3ce5fc"), uint32(0))
g2_element = G2Element(
    bytes.fromhex(
        "c00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
    )
)

declare_proof_of_space = farmer_protocol.DeclareProofOfSpace(
    bytes32([0] * 16 + [1] * 16),
    bytes32(b"a" * 16 + b"b" * 16),
    uint8(60),
    bytes32([0] * 16 + [1] * 16),
    proof_of_space,
    G2Element(
        bytes.fromhex(
            "c00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
        )
    ),
    G2Element(
        bytes.fromhex(
            "c00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
        )
    ),
    bytes32([0] * 32),
    pool_target,
    G2Element(
        bytes.fromhex(
            "c00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
        )
    ),
)

request_signed_values = farmer_protocol.RequestSignedValues(
    bytes32([0] * 16 + [1] * 16),
    bytes32(b"a" * 16 + b"b" * 16),
    bytes32([0] * 32),
)

farming_info = farmer_protocol.FarmingInfo(
    bytes32([0] * 16 + [1] * 16),
    bytes32(b"a" * 16 + b"b" * 16),
    uint64(100000),
    uint32(0),
    uint32(1),
    uint32(2),
)

signed_values = farmer_protocol.SignedValues(
    bytes32([0] * 16 + [1] * 16),
    G2Element(
        bytes.fromhex(
            "c00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
        )
    ),
    G2Element(
        bytes.fromhex(
            "c00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
        )
    ),
)


### FULL NODE PROTOCOL.
new_peak = full_node_protocol.NewPeak(
    bytes32(b"a" * 32),
    uint32(100000),
    uint128(100000000),
    uint32(10000),
    bytes32([0] * 32),
)

new_transaction = full_node_protocol.NewTransaction(
    bytes32(b"a" * 32),
    uint64(0),
    uint64(0),
)

request_transaction = full_node_protocol.RequestTransaction(
    bytes32(b"a" * 32),
)

coin_1 = Coin(
    bytes32(bytes.fromhex("ccd5bb71183532bff220ba46c268991a00000000000000000000000000989680")),
    bytes32(bytes.fromhex("ef282f4073e3fb8a1af602204de92c60810d3ebf22d8ad327a97440c474431d1")),
    uint64(1024),
)

serialized_program_1 = SerializedProgram.from_bytes(
    bytes.fromhex(
        "ff01ffff33ffa0f8912302fb33b8188046662785704afc3dd945074e4b45499a7173946e044695ff8203e880ffff33ffa03eaa52e850322dbc281c6b922e9d8819c7b4120ee054c4aa79db50be516a2bcaff8207d08080"
    )
)
serialized_program_2 = SerializedProgram.from_bytes(
    bytes.fromhex(
        "ffff01ffff33ffa0f8912302fb33b8188046662785704afc3dd945074e4b45499a7173946e044695ff8203e880ffff33ffa03eaa52e850322dbc281c6b922e9d8819c7b4120ee054c4aa79db50be516a2bcaff8207d08080ff8080"
    )
)

coin_spend = CoinSpend(
    coin_1,
    serialized_program_1,
    serialized_program_2,
)

coin_spends = [coin_spend]

spend_bundle = SpendBundle(
    coin_spends,
    G2Element(
        bytes.fromhex(
            "c00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
        )
    ),
)

respond_transaction = full_node_protocol.RespondTransaction(spend_bundle)

request_proof_of_weight = full_node_protocol.RequestProofOfWeight(
    uint32(10000),
    bytes32([0] * 32),
)

sub_epochs = SubEpochData(
    bytes32(b"a" * 32),
    uint8(8),
    uint64(0),
    uint64(0),
)

vdf_info = VDFInfo(
    bytes32(b"0" * 32),
    uint64(10000),
    ClassgroupElement.get_default_element(),
)

vdf_proof = VDFProof(
    uint8(0),
    bytes(b"0" * 100),
    False,
)

sub_slot_data = SubSlotData(
    proof_of_space,
    vdf_proof,
    vdf_proof,
    vdf_proof,
    vdf_info,
    uint8(0),
    vdf_proof,
    vdf_proof,
    vdf_info,
    vdf_info,
    vdf_info,
    vdf_info,
    uint128(100000),
)

sub_epoch_challenge_segments = SubEpochChallengeSegment(
    uint32(10),
    [sub_slot_data],
    vdf_info,
)

challenge_chain = ChallengeChainSubSlot(
    vdf_info,
    bytes32([0] * 32),
    bytes32([0] * 32),
    uint64(1000),
    uint64(1000),
)

infused_challenge_chain = InfusedChallengeChainSubSlot(
    vdf_info,
)

reward_chain = RewardChainSubSlot(
    vdf_info,
    bytes32([0] * 32),
    bytes32([0] * 32),
    uint8(8),
)

proofs = SubSlotProofs(
    vdf_proof,
    vdf_proof,
    vdf_proof,
)

reward_chain_block = RewardChainBlock(
    uint128(10000000000),
    uint32(50000),
    uint128(10000000000),
    uint8(10),
    bytes32(b"a" * 16 + b"b" * 16),
    proof_of_space,
    vdf_info,
    g2_element,
    vdf_info,
    vdf_info,
    g2_element,
    vdf_info,
    vdf_info,
    False,
)

foliage_block_data = FoliageBlockData(
    bytes32([0] * 32),
    pool_target,
    g2_element,
    bytes32([0] * 32),
    bytes32([0] * 32),
)

foliage = Foliage(
    bytes32([0] * 32),
    bytes32([0] * 32),
    foliage_block_data,
    g2_element,
    bytes32([0] * 32),
    g2_element,
)

foliage_transaction_block = FoliageTransactionBlock(
    bytes32([0] * 32),
    uint64(100000),
    bytes32([0] * 32),
    bytes32([0] * 32),
    bytes32([0] * 32),
    bytes32([0] * 32),
)

end_of_subslot_bundle = EndOfSubSlotBundle(
    challenge_chain,
    infused_challenge_chain,
    reward_chain,
    proofs,
)

transactions_info = TransactionsInfo(
    bytes32([0] * 32),
    bytes32([0] * 32),
    g2_element,
    uint64(1000),
    uint64(1000),
    [
        Coin(
            bytes32(bytes.fromhex("ccd5bb71183532bff220ba46c268991a00000000000000000000000000989680")),
            bytes32(bytes.fromhex("ef282f4073e3fb8a1af602204de92c60810d3ebf22d8ad327a97440c474431d1")),
            uint64(1024),
        ),
    ],
)

header_block = HeaderBlock(
    [end_of_subslot_bundle],
    reward_chain_block,
    vdf_proof,
    vdf_proof,
    vdf_proof,
    vdf_proof,
    vdf_proof,
    foliage,
    foliage_transaction_block,
    bytes([0] * 50),
    transactions_info,
)

recent_chain_data = RecentChainData(
    [header_block],
)

weight_proof = WeightProof(
    [sub_epochs],
    [sub_epoch_challenge_segments],
    [header_block],
)

respond_proof_of_weight = full_node_protocol.RespondProofOfWeight(
    weight_proof,
    bytes32(b"a" * 32),
)

request_block = full_node_protocol.RequestBlock(
    uint32(1000),
    False,
)

reject_block = full_node_protocol.RejectBlock(
    uint32(50000),
)

request_blocks = full_node_protocol.RequestBlocks(
    uint32(1000),
    uint32(2000),
    False,
)

full_block = FullBlock(
    [end_of_subslot_bundle],
    reward_chain_block,
    vdf_proof,
    vdf_proof,
    vdf_proof,
    vdf_proof,
    vdf_proof,
    foliage,
    foliage_transaction_block,
    transactions_info,
    SerializedProgram.from_bytes(
        bytes.fromhex(
            "ff01ffff33ffa0f8912302fb33b8188046662785704afc3dd945074e4b45499a7173946e044695ff8203e880ffff33ffa03eaa52e850322dbc281c6b922e9d8819c7b4120ee054c4aa79db50be516a2bcaff8207d08080"
        )
    ),
    [uint32(10000)],
)

respond_blocks = full_node_protocol.RespondBlocks(uint32(1000), uint32(2000), [full_block, full_block])

reject_blocks = full_node_protocol.RejectBlocks(
    uint32(50000),
    uint32(60000),
)

respond_block = full_node_protocol.RespondBlock(
    full_block,
)

new_unfinished_block = full_node_protocol.NewUnfinishedBlock(
    bytes32([0] * 32),
)

request_unfinished_block = full_node_protocol.RequestUnfinishedBlock(
    bytes32([0] * 32),
)

unfinished_block = UnfinishedBlock(
    [end_of_subslot_bundle],
    reward_chain_block.get_unfinished(),
    vdf_proof,
    vdf_proof,
    foliage,
    foliage_transaction_block,
    transactions_info,
    SerializedProgram.from_bytes(
        bytes.fromhex(
            "ff01ffff33ffa0f8912302fb33b8188046662785704afc3dd945074e4b45499a7173946e044695ff8203e880ffff33ffa03eaa52e850322dbc281c6b922e9d8819c7b4120ee054c4aa79db50be516a2bcaff8207d08080"
        )
    ),
    [uint32(10000)],
)

respond_unfinished_block = full_node_protocol.RespondUnfinishedBlock(unfinished_block)

new_signage_point_or_end_of_subslot = full_node_protocol.NewSignagePointOrEndOfSubSlot(
    bytes32([0] * 32),
    bytes32([0] * 32),
    uint8(8),
    bytes32([0] * 32),
)

request_signage_point_or_end_of_subslot = full_node_protocol.RequestSignagePointOrEndOfSubSlot(
    bytes32([0] * 32),
    uint8(8),
    bytes32([0] * 32),
)

respond_signage_point = full_node_protocol.RespondSignagePoint(
    uint8(60),
    vdf_info,
    vdf_proof,
    vdf_info,
    vdf_proof,
)

respond_end_of_subslot = full_node_protocol.RespondEndOfSubSlot(
    end_of_subslot_bundle,
)

request_mempool_transaction = full_node_protocol.RequestMempoolTransactions(
    bytes([0] * 32),
)

new_compact_vdf = full_node_protocol.NewCompactVDF(
    uint32(100),
    bytes32([0] * 32),
    uint8(8),
    vdf_info,
)

request_compact_vdf = full_node_protocol.RequestCompactVDF(
    uint32(100),
    bytes32([0] * 32),
    uint8(8),
    vdf_info,
)

respond_compact_vdf = full_node_protocol.RespondCompactVDF(
    uint32(100),
    bytes32([0] * 32),
    uint8(8),
    vdf_info,
    vdf_proof,
)

request_peers = full_node_protocol.RequestPeers()

timestamped_peer_info = TimestampedPeerInfo("127.0.0.1", uint16(8444), uint64(100000))

respond_peers = full_node_protocol.RespondPeers([timestamped_peer_info])


## WALLET PROTOCOL
request_puzzle_solution = wallet_protocol.RequestPuzzleSolution(
    bytes32(b"a" * 32),
    uint32(10000),
)

program = Program.from_serialized_program(
    SerializedProgram.from_bytes(
        bytes.fromhex(
            "ff01ffff33ffa0f8912302fb33b8188046662785704afc3dd945074e4b45499a7173946e044695ff8203e880ffff33ffa03eaa52e850322dbc281c6b922e9d8819c7b4120ee054c4aa79db50be516a2bcaff8207d08080"
        )
    ),
)

puzzle_solution_response = wallet_protocol.PuzzleSolutionResponse(
    bytes32(b"a" * 32),
    uint32(10000),
    program,
    program,
)

respond_puzzle_solution = wallet_protocol.RespondPuzzleSolution(
    puzzle_solution_response,
)

reject_puzzle_solution = wallet_protocol.RejectPuzzleSolution(
    bytes32([0] * 32),
    uint32(100000),
)

send_transaction = wallet_protocol.SendTransaction(
    spend_bundle,
)

transaction_ack = wallet_protocol.TransactionAck(
    bytes32([0] * 32),
    uint8(0),
    "None",
)

new_peak_wallet = wallet_protocol.NewPeakWallet(
    bytes32([0] * 32),
    uint32(10000),
    uint128(10000000),
    uint32(5000),
)

request_block_header = wallet_protocol.RequestBlockHeader(
    uint32(10000),
)

respond_header_block = wallet_protocol.RespondBlockHeader(
    header_block,
)

reject_header_request = wallet_protocol.RejectHeaderRequest(
    uint32(10000),
)

request_removals = wallet_protocol.RequestRemovals(
    uint32(10000),
    bytes32([0] * 32),
    [bytes32([0] * 32)],
)

respond_removals = wallet_protocol.RespondRemovals(
    uint32(10000),
    bytes32([0] * 32),
    [(bytes32([0] * 32), coin_1)],
    [(bytes32([0] * 32), bytes(b"a" * 10))],
)

reject_removals_request = wallet_protocol.RejectRemovalsRequest(
    uint32(10000),
    bytes32(b"a" * 32),
)

request_additions = wallet_protocol.RequestAdditions(
    uint32(10000),
    bytes32([0] * 32),
    [bytes32([0] * 32)],
)

respond_additions = wallet_protocol.RespondAdditions(
    uint32(10000),
    bytes32([0] * 32),
    [(bytes32([0] * 32), [coin_1, coin_1])],
    [(bytes32([0] * 32), bytes(b"a" * 10), bytes(b"a" * 10))],
)

reject_additions = wallet_protocol.RejectAdditionsRequest(
    uint32(10000),
    bytes32(b"a" * 32),
)

request_header_blocks = wallet_protocol.RequestHeaderBlocks(
    uint32(1000),
    uint32(2000),
)

reject_header_blocks = wallet_protocol.RejectHeaderBlocks(
    uint32(1000),
    uint32(2000),
)

respond_header_blocks = wallet_protocol.RespondHeaderBlocks(
    uint32(1000),
    uint32(1000),
    [header_block],
)

coin_state = wallet_protocol.CoinState(
    coin_1,
    uint32(10000),
    uint32(5000),
)

register_for_ph_updates = wallet_protocol.RegisterForPhUpdates(
    [bytes32([0] * 32)],
    uint32(5000),
)

respond_to_ph_updates = wallet_protocol.RespondToPhUpdates(
    [bytes32([0] * 32)],
    uint32(5000),
    [coin_state],
)

register_for_coin_updates = wallet_protocol.RegisterForCoinUpdates(
    [bytes32([0] * 32)],
    uint32(5000),
)

respond_to_coin_updates = wallet_protocol.RespondToCoinUpdates(
    [bytes32([0] * 32)],
    uint32(5000),
    [coin_state],
)

coin_state_update = wallet_protocol.CoinStateUpdate(
    uint32(10000),
    uint32(9000),
    bytes32(b"a" * 32),
    [coin_state],
)

request_children = wallet_protocol.RequestChildren(
    bytes32(b"a" * 32),
)

respond_children = wallet_protocol.RespondChildren(
    [coin_state],
)

request_ses_info = wallet_protocol.RequestSESInfo(
    uint32(1000),
    uint32(100000),
)

respond_ses_info = wallet_protocol.RespondSESInfo(
    [bytes32([0] * 32)], [[uint32(1), uint32(2), uint32(3)], [uint32(4), uint32(5)]]
)


### HARVESTER PROTOCOL
pool_difficulty = harvester_protocol.PoolDifficulty(
    uint64(1000000000),
    uint64(1000000000),
    bytes32([0] * 32),
)

harvester_handhsake = harvester_protocol.HarvesterHandshake(
    [
        G1Element(
            bytes.fromhex(
                "a04c6b5ac7dfb935f6feecfdd72348ccf1d4be4fe7e26acf271ea3b7d308da61e0a308f7a62495328a81f5147b66634c"
            ),
        ),
    ],
    [
        G1Element(
            bytes.fromhex(
                "a04c6b5ac7dfb935f6feecfdd72348ccf1d4be4fe7e26acf271ea3b7d308da61e0a308f7a62495328a81f5147b66634c"
            ),
        ),
    ],
)

new_signage_point_harvester = harvester_protocol.NewSignagePointHarvester(
    bytes32([0] * 32),
    uint64(1000000000),
    uint64(1000000000),
    uint8(60),
    bytes32(b"a" * 32),
    [pool_difficulty],
)

new_proof_of_space = harvester_protocol.NewProofOfSpace(
    bytes32([0] * 32),
    bytes32([0] * 32),
    "plot_1",
    proof_of_space,
    uint8(60),
)

request_signatures = harvester_protocol.RequestSignatures(
    "plot_1",
    bytes32([0] * 32),
    bytes32([0] * 32),
    [bytes32([0] * 32)],
)

respond_signatures = harvester_protocol.RespondSignatures(
    "plot_1",
    bytes32([0] * 32),
    bytes32([0] * 32),
    G1Element(
        bytes.fromhex(
            "a04c6b5ac7dfb935f6feecfdd72348ccf1d4be4fe7e26acf271ea3b7d308da61e0a308f7a62495328a81f5147b66634c"
        ),
    ),
    G1Element(
        bytes.fromhex(
            "a04c6b5ac7dfb935f6feecfdd72348ccf1d4be4fe7e26acf271ea3b7d308da61e0a308f7a62495328a81f5147b66634c"
        ),
    ),
    [(bytes32([0] * 32), g2_element)],
)

plot = harvester_protocol.Plot(
    "plot_1",
    uint8(10),
    bytes32([0] * 32),
    G1Element(
        bytes.fromhex(
            "a04c6b5ac7dfb935f6feecfdd72348ccf1d4be4fe7e26acf271ea3b7d308da61e0a308f7a62495328a81f5147b66634c"
        ),
    ),
    bytes32([0] * 32),
    G1Element(
        bytes.fromhex(
            "a04c6b5ac7dfb935f6feecfdd72348ccf1d4be4fe7e26acf271ea3b7d308da61e0a308f7a62495328a81f5147b66634c"
        ),
    ),
    uint64(1000000),
    uint64(1000000),
)

request_plots = harvester_protocol.RequestPlots()

respond_plots = harvester_protocol.RespondPlots(
    [plot],
    ["str"],
    ["str"],
)

### INTRODUCER PROTOCOL
request_peers_introducer = introducer_protocol.RequestPeersIntroducer()

respond_peers_introducer = introducer_protocol.RespondPeersIntroducer(
    [
        TimestampedPeerInfo(
            "127.0.0.1",
            uint16(8444),
            uint64(1000000),
        )
    ]
)


### POOL PROTOCOL
authentication_payload = pool_protocol.AuthenticationPayload(
    "method",
    bytes32([0] * 32),
    bytes32([0] * 32),
    uint64(100000),
)

get_pool_info_response = pool_protocol.GetPoolInfoResponse(
    "pool_name",
    "pool_name",
    uint64(100000),
    uint32(10000),
    uint8(10),
    "fee",
    "pool description.",
    bytes32([0] * 32),
    uint8(0),
)

post_partial_payload = pool_protocol.PostPartialPayload(
    bytes32([0] * 32),
    uint64(1234),
    proof_of_space,
    bytes32([0] * 32),
    False,
    bytes32([0] * 32),
)

post_partial_request = pool_protocol.PostPartialRequest(
    post_partial_payload,
    g2_element,
)

post_partial_response = pool_protocol.PostPartialResponse(
    uint64(100000),
)

get_farmer_response = pool_protocol.GetFarmerResponse(
    G1Element(
        bytes.fromhex(
            "a04c6b5ac7dfb935f6feecfdd72348ccf1d4be4fe7e26acf271ea3b7d308da61e0a308f7a62495328a81f5147b66634c"
        ),
    ),
    "instructions",
    uint64(100000),
    uint64(100000),
)

post_farmer_payload = pool_protocol.PostFarmerPayload(
    bytes32([0] * 32),
    uint64(100000),
    G1Element(
        bytes.fromhex(
            "a04c6b5ac7dfb935f6feecfdd72348ccf1d4be4fe7e26acf271ea3b7d308da61e0a308f7a62495328a81f5147b66634c"
        ),
    ),
    "payout_instructions",
    uint64(1000000),
)

post_farmer_request = pool_protocol.PostFarmerRequest(
    post_farmer_payload,
    g2_element,
)

post_farmer_response = pool_protocol.PostFarmerResponse(
    "welcome",
)

put_farmer_payload = pool_protocol.PutFarmerPayload(
    bytes32([0] * 32),
    uint64(100000),
    G1Element(
        bytes.fromhex(
            "a04c6b5ac7dfb935f6feecfdd72348ccf1d4be4fe7e26acf271ea3b7d308da61e0a308f7a62495328a81f5147b66634c"
        ),
    ),
    "payload",
    uint64(1000000),
)

put_farmer_request = pool_protocol.PutFarmerRequest(
    put_farmer_payload,
    g2_element,
)

put_farmer_response = pool_protocol.PutFarmerResponse(
    False,
    False,
    True,
)

error_response = pool_protocol.ErrorResponse(
    uint16(404),
    "err",
)

### TIMELORD PROTOCOL
sub_epoch_summary = SubEpochSummary(
    bytes32([0] * 32),
    bytes32([0] * 32),
    uint8(10),
    uint64(1000000),
    uint64(1000000),
)

new_peak_timelord = timelord_protocol.NewPeakTimelord(
    reward_chain_block,
    uint64(1000000),
    uint8(8),
    uint64(1000000),
    sub_epoch_summary,
    [(bytes32(b"a" * 32), uint128(10000000000))],
    uint128(10000000000),
    True,
)

new_unfinished_block_timelord = timelord_protocol.NewUnfinishedBlockTimelord(
    reward_chain_block.get_unfinished(),
    uint64(1000000),
    uint64(1000000),
    foliage,
    sub_epoch_summary,
    bytes32([0] * 32),
)

new_infusion_point_vdf = timelord_protocol.NewInfusionPointVDF(
    bytes32([0] * 32),
    vdf_info,
    vdf_proof,
    vdf_info,
    vdf_proof,
    vdf_info,
    vdf_proof,
)

new_signage_point_vdf = timelord_protocol.NewSignagePointVDF(
    uint8(10),
    vdf_info,
    vdf_proof,
    vdf_info,
    vdf_proof,
)

new_end_of_sub_slot_bundle = timelord_protocol.NewEndOfSubSlotVDF(
    end_of_subslot_bundle,
)

request_compact_proof_of_time = timelord_protocol.RequestCompactProofOfTime(
    vdf_info,
    bytes32(b"a" * 32),
    uint32(100000),
    uint8(0),
)

respond_compact_proof_of_time = timelord_protocol.RespondCompactProofOfTime(
    vdf_info,
    vdf_proof,
    bytes32(b"a" * 32),
    uint32(100000),
    uint8(0),
)
