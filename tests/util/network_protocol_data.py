from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint8, uint32, uint64, uint128
from chia.types.blockchain_format.proof_of_space import ProofOfSpace
from chia.types.blockchain_format.pool_target import PoolTarget
from chia.types.coin_spend import CoinSpend
from chia.types.blockchain_format.coin import Coin
from chia.types.spend_bundle import SpendBundle
from chia.types.blockchain_format.program import SerializedProgram
from chia.types.weight_proof import WeightProof, SubEpochData, SubEpochChallengeSegment, SubSlotData, RecentChainData
from chia.types.blockchain_format.vdf import VDFInfo, VDFProof
from chia.types.blockchain_format.classgroup import ClassgroupElement
from blspy import G1Element, G2Element
from chia.types.header_block import HeaderBlock
from chia.types.full_block import FullBlock
from chia.types.unfinished_block import UnfinishedBlock
from chia.types.blockchain_format.slots import ChallengeChainSubSlot, InfusedChallengeChainSubSlot, RewardChainSubSlot, SubSlotProofs
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
g2_element = G2Element(bytes.fromhex("c00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"))

declare_proof_of_space = farmer_protocol.DeclareProofOfSpace(
    bytes32([0] * 16 + [1] * 16),
    bytes32(b"a" * 16 + b"b" * 16),
    uint8(60),
    bytes32([0] * 16 + [1] * 16),
    proof_of_space,
    G2Element(bytes.fromhex("c00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000")),
    G2Element(bytes.fromhex("c00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000")),
    bytes32([0] * 32),
    pool_target,
    G2Element(bytes.fromhex("c00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000")),
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
    G2Element(bytes.fromhex("c00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000")),
    G2Element(bytes.fromhex("c00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000")),
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

coin_spends = [
    CoinSpend(
        Coin(
            bytes32(bytes.fromhex("ccd5bb71183532bff220ba46c268991a00000000000000000000000000989680")),
            bytes32(bytes.fromhex("ef282f4073e3fb8a1af602204de92c60810d3ebf22d8ad327a97440c474431d1")),
            uint64(1024),
        ),
        SerializedProgram.from_bytes(bytes.fromhex("ff01ffff33ffa0f8912302fb33b8188046662785704afc3dd945074e4b45499a7173946e044695ff8203e880ffff33ffa03eaa52e850322dbc281c6b922e9d8819c7b4120ee054c4aa79db50be516a2bcaff8207d08080")),
        SerializedProgram.from_bytes(bytes.fromhex("ffff01ffff33ffa0f8912302fb33b8188046662785704afc3dd945074e4b45499a7173946e044695ff8203e880ffff33ffa03eaa52e850322dbc281c6b922e9d8819c7b4120ee054c4aa79db50be516a2bcaff8207d08080ff8080")),
    )
]

spend_bundle = SpendBundle(
    coin_spends,
    G2Element(bytes.fromhex("c00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000")),
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
    0,
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
    ]
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
    SerializedProgram.from_bytes(bytes.fromhex("ff01ffff33ffa0f8912302fb33b8188046662785704afc3dd945074e4b45499a7173946e044695ff8203e880ffff33ffa03eaa52e850322dbc281c6b922e9d8819c7b4120ee054c4aa79db50be516a2bcaff8207d08080")),
    [uint32(10000)],
)

respond_blocks = full_node_protocol.RespondBlocks(
    uint32(1000),
    uint32(2000),
    [full_block, full_block]
)

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
    SerializedProgram.from_bytes(bytes.fromhex("ff01ffff33ffa0f8912302fb33b8188046662785704afc3dd945074e4b45499a7173946e044695ff8203e880ffff33ffa03eaa52e850322dbc281c6b922e9d8819c7b4120ee054c4aa79db50be516a2bcaff8207d08080")),
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

timestamped_peer_info = TimestampedPeerInfo("127.0.0.1", 8444, uint64(100000))

respond_peers = full_node_protocol.RespondPeers(
    [timestamped_peer_info]
)
