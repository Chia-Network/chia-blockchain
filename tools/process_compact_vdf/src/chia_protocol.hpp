#pragma once

#include "streamable.hpp"

#include <array>
#include <cstdint>
#include <optional>
#include <string>
#include <vector>

namespace chia {

using Bytes32 = std::array<uint8_t, 32>;
using Bytes48 = std::array<uint8_t, 48>;
using Bytes96 = std::array<uint8_t, 96>;
using Bytes100 = std::array<uint8_t, 100>;

struct VDFInfo {
    Bytes32 challenge{};
    uint64_t number_of_iterations{};
    Bytes100 output{};

    static VDFInfo parse(streamable::Reader& r);
    void stream(streamable::Writer& w) const;
    bool operator==(const VDFInfo& o) const;
    bool operator!=(const VDFInfo& o) const;
};

struct VDFProof {
    uint8_t witness_type{};
    std::vector<uint8_t> witness;
    bool normalized_to_identity{};

    static VDFProof parse(streamable::Reader& r);
    void stream(streamable::Writer& w) const;
    static VDFProof compact(const std::vector<uint8_t>& witness_bytes);
    bool is_compact() const;
};

struct ClassgroupElement {
    Bytes100 data{};

    static ClassgroupElement parse(streamable::Reader& r);
    void stream(streamable::Writer& w) const;
    static ClassgroupElement default_element();
};

struct Program {
    std::vector<uint8_t> a0;

    static Program parse(streamable::Reader& r);
    void stream(streamable::Writer& w) const;
};

struct G1Element {
    Bytes48 data{};

    static G1Element parse(streamable::Reader& r);
    void stream(streamable::Writer& w) const;
};

struct G2Element {
    Bytes96 data{};

    static G2Element parse(streamable::Reader& r);
    void stream(streamable::Writer& w) const;
};

struct Coin {
    Bytes32 parent_coin_info{};
    Bytes32 puzzle_hash{};
    uint64_t amount{};

    static Coin parse(streamable::Reader& r);
    void stream(streamable::Writer& w) const;
};

struct PoolTarget {
    Bytes32 puzzle_hash{};
    uint32_t max_height{};

    static PoolTarget parse(streamable::Reader& r);
    void stream(streamable::Writer& w) const;
};

struct ProofOfSpace {
    Bytes32 challenge{};
    std::optional<G1Element> pool_public_key;
    std::optional<Bytes32> pool_contract_puzzle_hash;
    G1Element plot_public_key{};
    uint8_t version{};
    uint16_t plot_index{};
    uint8_t meta_group{};
    uint8_t strength{};
    uint8_t size{};
    std::vector<uint8_t> proof;

    static ProofOfSpace parse(streamable::Reader& r);
    void stream(streamable::Writer& w) const;
};

struct RewardChainBlock {
    streamable::u128 weight{};
    uint32_t height{};
    streamable::u128 total_iters{};
    uint8_t signage_point_index{};
    Bytes32 pos_ss_cc_challenge_hash{};
    ProofOfSpace proof_of_space{};
    std::optional<VDFInfo> challenge_chain_sp_vdf;
    G2Element challenge_chain_sp_signature{};
    VDFInfo challenge_chain_ip_vdf{};
    std::optional<VDFInfo> reward_chain_sp_vdf;
    G2Element reward_chain_sp_signature{};
    VDFInfo reward_chain_ip_vdf{};
    std::optional<VDFInfo> infused_challenge_chain_ip_vdf;
    std::optional<Bytes32> header_mmr_root;
    bool is_transaction_block{};

    static RewardChainBlock parse(streamable::Reader& r);
    void stream(streamable::Writer& w) const;
};

struct ChallengeChainSubSlot {
    VDFInfo challenge_chain_end_of_slot_vdf{};
    std::optional<Bytes32> infused_challenge_chain_sub_slot_hash;
    std::optional<Bytes32> subepoch_summary_hash;
    std::optional<uint64_t> new_sub_slot_iters;
    std::optional<uint64_t> new_difficulty;

    static ChallengeChainSubSlot parse(streamable::Reader& r);
    void stream(streamable::Writer& w) const;
};

struct InfusedChallengeChainSubSlot {
    VDFInfo infused_challenge_chain_end_of_slot_vdf{};

    static InfusedChallengeChainSubSlot parse(streamable::Reader& r);
    void stream(streamable::Writer& w) const;
};

struct RewardChainSubSlot {
    VDFInfo end_of_slot_vdf{};
    Bytes32 challenge_chain_sub_slot_hash{};
    std::optional<Bytes32> infused_challenge_chain_sub_slot_hash;
    uint8_t deficit{};

    static RewardChainSubSlot parse(streamable::Reader& r);
    void stream(streamable::Writer& w) const;
};

struct SubSlotProofs {
    VDFProof challenge_chain_slot_proof{};
    std::optional<VDFProof> infused_challenge_chain_slot_proof;
    VDFProof reward_chain_slot_proof{};

    static SubSlotProofs parse(streamable::Reader& r);
    void stream(streamable::Writer& w) const;
};

struct EndOfSubSlotBundle {
    ChallengeChainSubSlot challenge_chain{};
    std::optional<InfusedChallengeChainSubSlot> infused_challenge_chain;
    RewardChainSubSlot reward_chain{};
    SubSlotProofs proofs{};

    static EndOfSubSlotBundle parse(streamable::Reader& r);
    void stream(streamable::Writer& w) const;
};

struct FoliageBlockData {
    Bytes32 unfinished_reward_block_hash{};
    PoolTarget pool_target{};
    std::optional<G2Element> pool_signature;
    Bytes32 farmer_reward_puzzle_hash{};
    Bytes32 extension_data{};

    static FoliageBlockData parse(streamable::Reader& r);
    void stream(streamable::Writer& w) const;
};

struct FoliageTransactionBlock {
    Bytes32 prev_transaction_block_hash{};
    uint64_t timestamp{};
    Bytes32 filter_hash{};
    Bytes32 additions_root{};
    Bytes32 removals_root{};
    Bytes32 transactions_info_hash{};

    static FoliageTransactionBlock parse(streamable::Reader& r);
    void stream(streamable::Writer& w) const;
};

struct TransactionsInfo {
    Bytes32 generator_root{};
    Bytes32 generator_refs_root{};
    G2Element aggregated_signature{};
    uint64_t fees{};
    uint64_t cost{};
    std::vector<Coin> reward_claims_incorporated;

    static TransactionsInfo parse(streamable::Reader& r);
    void stream(streamable::Writer& w) const;
};

struct Foliage {
    Bytes32 prev_block_hash{};
    Bytes32 reward_block_hash{};
    FoliageBlockData foliage_block_data{};
    G2Element foliage_block_data_signature{};
    std::optional<Bytes32> foliage_transaction_block_hash;
    std::optional<G2Element> foliage_transaction_block_signature;

    static Foliage parse(streamable::Reader& r);
    void stream(streamable::Writer& w) const;
};

struct FullBlock {
    std::vector<EndOfSubSlotBundle> finished_sub_slots;
    RewardChainBlock reward_chain_block{};
    std::optional<VDFProof> challenge_chain_sp_proof;
    VDFProof challenge_chain_ip_proof{};
    std::optional<VDFProof> reward_chain_sp_proof;
    VDFProof reward_chain_ip_proof{};
    std::optional<VDFProof> infused_challenge_chain_ip_proof;
    Foliage foliage{};
    std::optional<FoliageTransactionBlock> foliage_transaction_block;
    std::optional<TransactionsInfo> transactions_info;
    std::optional<Program> transactions_generator;
    std::vector<uint32_t> transactions_generator_ref_list;
    std::optional<std::vector<uint8_t>> transactions_generator_buffer;
    uint8_t version{};

    static FullBlock from_bytes(const std::vector<uint8_t>& bytes);
    std::vector<uint8_t> to_bytes() const;
    bool is_fully_compactified() const;
    Bytes32 header_hash() const;
    uint32_t height() const;
};

enum class CompressibleVDFField : uint8_t {
    CC_EOS_VDF = 1,
    ICC_EOS_VDF = 2,
    CC_SP_VDF = 3,
    CC_IP_VDF = 4,
};

struct CompactVdfEntry {
    Bytes32 header_hash{};
    uint8_t field_vdf{};
    std::vector<uint8_t> witness;
};

std::vector<CompactVdfEntry> extract_witness_type_zero_entries(const chia::Bytes32& header_hash,
                                                               const FullBlock& block);

std::vector<VDFInfo> vdf_info_candidates(const FullBlock& block, CompressibleVDFField field);
bool needs_compact_proof(const VDFInfo& info, const FullBlock& block, CompressibleVDFField field);
bool apply_compact_proof(FullBlock& block, const VDFInfo& info, const VDFProof& proof, CompressibleVDFField field);

std::vector<uint8_t> hex_to_bytes(const std::string& hex);
std::string bytes_to_hex(const uint8_t* data, size_t len);
std::string bytes32_to_db_hex(const Bytes32& hash);

struct Bytes32Hash {
    std::size_t operator()(const Bytes32& hash) const noexcept;
};

}  // namespace chia
