#include "chia_protocol.hpp"

#include "clvm_length.hpp"

#include <algorithm>
#include <cstring>
#include <functional>
#include <sstream>
#include <stdexcept>

namespace chia {
namespace {

template <typename T>
std::optional<T> parse_optional(streamable::Reader& r, T (*parse_fn)(streamable::Reader&)) {
    const uint8_t prefix = r.read_u8();
    if (prefix == 0) {
        return std::nullopt;
    }
    if (prefix == 1) {
        return parse_fn(r);
    }
    throw streamable::ParseError("invalid optional prefix");
}

template <typename T>
auto stream_fn() {
    return [](streamable::Writer& w, const T& value) { value.stream(w); };
}

template <typename T, typename F>
void stream_optional(streamable::Writer& w, const std::optional<T>& value, F stream_fn_impl) {
    if (!value.has_value()) {
        w.write_u8(0);
        return;
    }
    w.write_u8(1);
    stream_fn_impl(w, *value);
}

template <typename T>
void stream_optional(streamable::Writer& w, const std::optional<T>& value) {
    stream_optional(w, value, stream_fn<T>());
}

void stream_optional_bytes32(streamable::Writer& w, const std::optional<Bytes32>& value) {
    stream_optional(w, value, [](streamable::Writer& writer, const Bytes32& v) { writer.write_fixed(v); });
}

void stream_optional_u64(streamable::Writer& w, const std::optional<uint64_t>& value) {
    stream_optional(w, value, [](streamable::Writer& writer, uint64_t v) { writer.write_u64_be(v); });
}

template <typename T, typename U>
std::pair<std::optional<T>, std::optional<U>> parse_dual_optional(
    streamable::Reader& r, T (*parse_t)(streamable::Reader&), U (*parse_u)(streamable::Reader&)) {
    const uint8_t index = r.read_u8();
    switch (index) {
        case 0:
            return {std::nullopt, std::nullopt};
        case 1:
            return {parse_t(r), std::nullopt};
        case 2:
            return {std::nullopt, parse_u(r)};
        case 3:
            return {parse_t(r), parse_u(r)};
        default:
            throw streamable::ParseError("invalid dual optional index");
    }
}

template <typename T, typename U, typename FT, typename FU>
void stream_dual_optional(streamable::Writer& w, const std::optional<T>& first, const std::optional<U>& second,
                          FT stream_t, FU stream_u) {
    if (!first.has_value() && !second.has_value()) {
        w.write_u8(0);
    } else if (first.has_value() && !second.has_value()) {
        w.write_u8(1);
        stream_t(w, *first);
    } else if (!first.has_value() && second.has_value()) {
        w.write_u8(2);
        stream_u(w, *second);
    } else {
        w.write_u8(3);
        stream_t(w, *first);
        stream_u(w, *second);
    }
}

template <typename T, typename U>
void stream_dual_optional(streamable::Writer& w, const std::optional<T>& first, const std::optional<U>& second) {
    stream_dual_optional(w, first, second, stream_fn<T>(), stream_fn<U>());
}

template <typename T>
std::vector<T> parse_list(streamable::Reader& r, T (*parse_fn)(streamable::Reader&)) {
    const uint32_t len = r.read_u32_be();
    std::vector<T> out;
    out.reserve(len);
    for (uint32_t i = 0; i < len; ++i) {
        out.push_back(parse_fn(r));
    }
    return out;
}

template <typename T, typename F>
void stream_list(streamable::Writer& w, const std::vector<T>& values, F stream_fn_impl) {
    if (values.size() > std::numeric_limits<uint32_t>::max()) {
        throw streamable::ParseError("list too large");
    }
    w.write_u32_be(static_cast<uint32_t>(values.size()));
    for (const auto& value : values) {
        stream_fn_impl(w, value);
    }
}

template <typename T>
void stream_list(streamable::Writer& w, const std::vector<T>& values) {
    stream_list(w, values, stream_fn<T>());
}

bool proof_is_compact(const VDFProof& proof) {
    return proof.witness_type == 0 && proof.normalized_to_identity;
}

}  // namespace

bool VDFInfo::operator==(const VDFInfo& o) const {
    return challenge == o.challenge && number_of_iterations == o.number_of_iterations && output == o.output;
}

bool VDFInfo::operator!=(const VDFInfo& o) const { return !(*this == o); }

VDFInfo VDFInfo::parse(streamable::Reader& r) {
    VDFInfo info;
    info.challenge = r.read_fixed<32>();
    info.number_of_iterations = r.read_u64_be();
    info.output = r.read_fixed<100>();
    return info;
}

void VDFInfo::stream(streamable::Writer& w) const {
    w.write_fixed(challenge);
    w.write_u64_be(number_of_iterations);
    w.write_fixed(output);
}

VDFProof VDFProof::parse(streamable::Reader& r) {
    VDFProof proof;
    proof.witness_type = r.read_u8();
    proof.witness = r.read_bytes();
    proof.normalized_to_identity = r.read_bool();
    return proof;
}

void VDFProof::stream(streamable::Writer& w) const {
    w.write_u8(witness_type);
    w.write_bytes(witness);
    w.write_bool(normalized_to_identity);
}

VDFProof VDFProof::compact(const std::vector<uint8_t>& witness_bytes) {
    VDFProof proof;
    proof.witness_type = 0;
    proof.witness = witness_bytes;
    proof.normalized_to_identity = true;
    return proof;
}

bool VDFProof::is_compact() const { return proof_is_compact(*this); }

ClassgroupElement ClassgroupElement::parse(streamable::Reader& r) {
    ClassgroupElement el;
    el.data = r.read_fixed<100>();
    return el;
}

void ClassgroupElement::stream(streamable::Writer& w) const { w.write_fixed(data); }

ClassgroupElement ClassgroupElement::default_element() {
    ClassgroupElement el;
    el.data[0] = 0x08;
    return el;
}

Program Program::parse(streamable::Reader& r) {
    Program p;
    const auto& data = r.buffer();
    const std::size_t offset = r.position();
    if (offset >= data.size()) {
        throw streamable::ParseError("unexpected end of buffer");
    }
    try {
        const std::size_t len = clvm_length::serialized_length_trusted(data, offset);
        if (offset + len > data.size()) {
            throw streamable::ParseError("unexpected end of buffer");
        }
        p.a0.assign(data.begin() + static_cast<std::ptrdiff_t>(offset),
                    data.begin() + static_cast<std::ptrdiff_t>(offset + len));
        r.skip_bytes(len);
    } catch (const std::runtime_error& e) {
        throw streamable::ParseError(e.what());
    }
    return p;
}

void Program::stream(streamable::Writer& w) const { w.write_bytes_raw(a0); }

G1Element G1Element::parse(streamable::Reader& r) {
    G1Element el;
    el.data = r.read_fixed<48>();
    return el;
}

void G1Element::stream(streamable::Writer& w) const { w.write_fixed(data); }

G2Element G2Element::parse(streamable::Reader& r) {
    G2Element el;
    el.data = r.read_fixed<96>();
    return el;
}

void G2Element::stream(streamable::Writer& w) const { w.write_fixed(data); }

Coin Coin::parse(streamable::Reader& r) {
    Coin c;
    c.parent_coin_info = r.read_fixed<32>();
    c.puzzle_hash = r.read_fixed<32>();
    c.amount = r.read_u64_be();
    return c;
}

void Coin::stream(streamable::Writer& w) const {
    w.write_fixed(parent_coin_info);
    w.write_fixed(puzzle_hash);
    w.write_u64_be(amount);
}

PoolTarget PoolTarget::parse(streamable::Reader& r) {
    PoolTarget t;
    t.puzzle_hash = r.read_fixed<32>();
    t.max_height = r.read_u32_be();
    return t;
}

void PoolTarget::stream(streamable::Writer& w) const {
    w.write_fixed(puzzle_hash);
    w.write_u32_be(max_height);
}

ProofOfSpace ProofOfSpace::parse(streamable::Reader& r) {
    ProofOfSpace pos;
    pos.challenge = r.read_fixed<32>();
    pos.pool_public_key = parse_optional<G1Element>(r, G1Element::parse);

    const uint8_t prefix = r.read_u8();
    pos.version = static_cast<uint8_t>((prefix & 0b10) != 0);
    if ((prefix & 1) != 0) {
        pos.pool_contract_puzzle_hash = r.read_fixed<32>();
    }

    pos.plot_public_key = G1Element::parse(r);

    if (pos.version == 0) {
        pos.size = r.read_u8();
        pos.proof = r.read_bytes();
        return pos;
    }
    if (pos.version == 1) {
        pos.plot_index = r.read_u16_be();
        pos.meta_group = r.read_u8();
        pos.strength = r.read_u8();
        pos.proof = r.read_bytes();
        if (pos.pool_public_key.has_value() == pos.pool_contract_puzzle_hash.has_value()) {
            throw streamable::ParseError("invalid proof of space pool fields");
        }
        return pos;
    }
    throw streamable::ParseError("invalid proof of space version");
}

void ProofOfSpace::stream(streamable::Writer& w) const {
    w.write_fixed(challenge);
    stream_optional<G1Element>(w, pool_public_key);

    if (version == 0) {
        uint8_t prefix = 0;
        if (pool_contract_puzzle_hash.has_value()) {
            prefix |= 1;
        }
        w.write_u8(prefix);
        if (pool_contract_puzzle_hash.has_value()) {
            w.write_fixed(*pool_contract_puzzle_hash);
        }
        plot_public_key.stream(w);
        w.write_u8(size);
        w.write_bytes(proof);
        return;
    }

    uint8_t prefix = 0b10;
    if (pool_contract_puzzle_hash.has_value()) {
        prefix = 0b11;
        w.write_u8(prefix);
        w.write_fixed(*pool_contract_puzzle_hash);
    } else {
        w.write_u8(prefix);
    }
    plot_public_key.stream(w);
    w.write_u16_be(plot_index);
    w.write_u8(meta_group);
    w.write_u8(strength);
    w.write_bytes(proof);
}

RewardChainBlock RewardChainBlock::parse(streamable::Reader& r) {
    RewardChainBlock block;
    block.weight = r.read_u128_be();
    block.height = r.read_u32_be();
    block.total_iters = r.read_u128_be();
    block.signage_point_index = r.read_u8();
    block.pos_ss_cc_challenge_hash = r.read_fixed<32>();
    block.proof_of_space = ProofOfSpace::parse(r);
    block.challenge_chain_sp_vdf = parse_optional<VDFInfo>(r, VDFInfo::parse);
    block.challenge_chain_sp_signature = G2Element::parse(r);
    block.challenge_chain_ip_vdf = VDFInfo::parse(r);
    block.reward_chain_sp_vdf = parse_optional<VDFInfo>(r, VDFInfo::parse);
    block.reward_chain_sp_signature = G2Element::parse(r);
    block.reward_chain_ip_vdf = VDFInfo::parse(r);
    std::tie(block.infused_challenge_chain_ip_vdf, block.header_mmr_root) =
        parse_dual_optional<VDFInfo, Bytes32>(r, VDFInfo::parse, [](streamable::Reader& reader) { return reader.read_fixed<32>(); });
    block.is_transaction_block = r.read_bool();
    return block;
}

void RewardChainBlock::stream(streamable::Writer& w) const {
    w.write_u128_be(weight);
    w.write_u32_be(height);
    w.write_u128_be(total_iters);
    w.write_u8(signage_point_index);
    w.write_fixed(pos_ss_cc_challenge_hash);
    proof_of_space.stream(w);
    stream_optional<VDFInfo>(w, challenge_chain_sp_vdf);
    challenge_chain_sp_signature.stream(w);
    challenge_chain_ip_vdf.stream(w);
    stream_optional<VDFInfo>(w, reward_chain_sp_vdf);
    reward_chain_sp_signature.stream(w);
    reward_chain_ip_vdf.stream(w);
    stream_dual_optional(w, infused_challenge_chain_ip_vdf, header_mmr_root, stream_fn<VDFInfo>(),
                         [](streamable::Writer& writer, const Bytes32& value) { writer.write_fixed(value); });
    w.write_bool(is_transaction_block);
}

ChallengeChainSubSlot ChallengeChainSubSlot::parse(streamable::Reader& r) {
    ChallengeChainSubSlot slot;
    slot.challenge_chain_end_of_slot_vdf = VDFInfo::parse(r);
    slot.infused_challenge_chain_sub_slot_hash = parse_optional<Bytes32>(r, [](streamable::Reader& reader) { return reader.read_fixed<32>(); });
    slot.subepoch_summary_hash = parse_optional<Bytes32>(r, [](streamable::Reader& reader) { return reader.read_fixed<32>(); });
    slot.new_sub_slot_iters = parse_optional<uint64_t>(r, [](streamable::Reader& reader) { return reader.read_u64_be(); });
    slot.new_difficulty = parse_optional<uint64_t>(r, [](streamable::Reader& reader) { return reader.read_u64_be(); });
    return slot;
}

void ChallengeChainSubSlot::stream(streamable::Writer& w) const {
    challenge_chain_end_of_slot_vdf.stream(w);
    stream_optional_bytes32(w, infused_challenge_chain_sub_slot_hash);
    stream_optional_bytes32(w, subepoch_summary_hash);
    stream_optional_u64(w, new_sub_slot_iters);
    stream_optional_u64(w, new_difficulty);
}

InfusedChallengeChainSubSlot InfusedChallengeChainSubSlot::parse(streamable::Reader& r) {
    InfusedChallengeChainSubSlot slot;
    slot.infused_challenge_chain_end_of_slot_vdf = VDFInfo::parse(r);
    return slot;
}

void InfusedChallengeChainSubSlot::stream(streamable::Writer& w) const {
    infused_challenge_chain_end_of_slot_vdf.stream(w);
}

RewardChainSubSlot RewardChainSubSlot::parse(streamable::Reader& r) {
    RewardChainSubSlot slot;
    slot.end_of_slot_vdf = VDFInfo::parse(r);
    slot.challenge_chain_sub_slot_hash = r.read_fixed<32>();
    slot.infused_challenge_chain_sub_slot_hash =
        parse_optional<Bytes32>(r, [](streamable::Reader& reader) { return reader.read_fixed<32>(); });
    slot.deficit = r.read_u8();
    return slot;
}

void RewardChainSubSlot::stream(streamable::Writer& w) const {
    end_of_slot_vdf.stream(w);
    w.write_fixed(challenge_chain_sub_slot_hash);
    stream_optional_bytes32(w, infused_challenge_chain_sub_slot_hash);
    w.write_u8(deficit);
}

SubSlotProofs SubSlotProofs::parse(streamable::Reader& r) {
    SubSlotProofs proofs;
    proofs.challenge_chain_slot_proof = VDFProof::parse(r);
    proofs.infused_challenge_chain_slot_proof = parse_optional<VDFProof>(r, VDFProof::parse);
    proofs.reward_chain_slot_proof = VDFProof::parse(r);
    return proofs;
}

void SubSlotProofs::stream(streamable::Writer& w) const {
    challenge_chain_slot_proof.stream(w);
    stream_optional<VDFProof>(w, infused_challenge_chain_slot_proof);
    reward_chain_slot_proof.stream(w);
}

EndOfSubSlotBundle EndOfSubSlotBundle::parse(streamable::Reader& r) {
    EndOfSubSlotBundle bundle;
    bundle.challenge_chain = ChallengeChainSubSlot::parse(r);
    bundle.infused_challenge_chain = parse_optional<InfusedChallengeChainSubSlot>(r, InfusedChallengeChainSubSlot::parse);
    bundle.reward_chain = RewardChainSubSlot::parse(r);
    bundle.proofs = SubSlotProofs::parse(r);
    return bundle;
}

void EndOfSubSlotBundle::stream(streamable::Writer& w) const {
    challenge_chain.stream(w);
    stream_optional<InfusedChallengeChainSubSlot>(w, infused_challenge_chain);
    reward_chain.stream(w);
    proofs.stream(w);
}

FoliageBlockData FoliageBlockData::parse(streamable::Reader& r) {
    FoliageBlockData data;
    data.unfinished_reward_block_hash = r.read_fixed<32>();
    data.pool_target = PoolTarget::parse(r);
    data.pool_signature = parse_optional<G2Element>(r, G2Element::parse);
    data.farmer_reward_puzzle_hash = r.read_fixed<32>();
    data.extension_data = r.read_fixed<32>();
    return data;
}

void FoliageBlockData::stream(streamable::Writer& w) const {
    w.write_fixed(unfinished_reward_block_hash);
    pool_target.stream(w);
    stream_optional<G2Element>(w, pool_signature);
    w.write_fixed(farmer_reward_puzzle_hash);
    w.write_fixed(extension_data);
}

FoliageTransactionBlock FoliageTransactionBlock::parse(streamable::Reader& r) {
    FoliageTransactionBlock block;
    block.prev_transaction_block_hash = r.read_fixed<32>();
    block.timestamp = r.read_u64_be();
    block.filter_hash = r.read_fixed<32>();
    block.additions_root = r.read_fixed<32>();
    block.removals_root = r.read_fixed<32>();
    block.transactions_info_hash = r.read_fixed<32>();
    return block;
}

void FoliageTransactionBlock::stream(streamable::Writer& w) const {
    w.write_fixed(prev_transaction_block_hash);
    w.write_u64_be(timestamp);
    w.write_fixed(filter_hash);
    w.write_fixed(additions_root);
    w.write_fixed(removals_root);
    w.write_fixed(transactions_info_hash);
}

TransactionsInfo TransactionsInfo::parse(streamable::Reader& r) {
    TransactionsInfo info;
    info.generator_root = r.read_fixed<32>();
    info.generator_refs_root = r.read_fixed<32>();
    info.aggregated_signature = G2Element::parse(r);
    info.fees = r.read_u64_be();
    info.cost = r.read_u64_be();
    info.reward_claims_incorporated = parse_list<Coin>(r, Coin::parse);
    return info;
}

void TransactionsInfo::stream(streamable::Writer& w) const {
    w.write_fixed(generator_root);
    w.write_fixed(generator_refs_root);
    aggregated_signature.stream(w);
    w.write_u64_be(fees);
    w.write_u64_be(cost);
    stream_list<Coin>(w, reward_claims_incorporated);
}

Foliage Foliage::parse(streamable::Reader& r) {
    Foliage foliage;
    foliage.prev_block_hash = r.read_fixed<32>();
    foliage.reward_block_hash = r.read_fixed<32>();
    foliage.foliage_block_data = FoliageBlockData::parse(r);
    foliage.foliage_block_data_signature = G2Element::parse(r);
    foliage.foliage_transaction_block_hash =
        parse_optional<Bytes32>(r, [](streamable::Reader& reader) { return reader.read_fixed<32>(); });
    foliage.foliage_transaction_block_signature = parse_optional<G2Element>(r, G2Element::parse);
    return foliage;
}

void Foliage::stream(streamable::Writer& w) const {
    w.write_fixed(prev_block_hash);
    w.write_fixed(reward_block_hash);
    foliage_block_data.stream(w);
    foliage_block_data_signature.stream(w);
    stream_optional_bytes32(w, foliage_transaction_block_hash);
    stream_optional<G2Element>(w, foliage_transaction_block_signature);
}

FullBlock FullBlock::from_bytes(const std::vector<uint8_t>& bytes) {
    streamable::Reader r(bytes);
    FullBlock block;
    block.finished_sub_slots = parse_list<EndOfSubSlotBundle>(r, EndOfSubSlotBundle::parse);
    block.reward_chain_block = RewardChainBlock::parse(r);
    block.challenge_chain_sp_proof = parse_optional<VDFProof>(r, VDFProof::parse);
    block.challenge_chain_ip_proof = VDFProof::parse(r);
    block.reward_chain_sp_proof = parse_optional<VDFProof>(r, VDFProof::parse);
    block.reward_chain_ip_proof = VDFProof::parse(r);
    block.infused_challenge_chain_ip_proof = parse_optional<VDFProof>(r, VDFProof::parse);
    block.foliage = Foliage::parse(r);
    block.foliage_transaction_block = parse_optional<FoliageTransactionBlock>(r, FoliageTransactionBlock::parse);
    block.transactions_info = parse_optional<TransactionsInfo>(r, TransactionsInfo::parse);

    const uint8_t prefix = r.read_u8();
    block.version = static_cast<uint8_t>((prefix & 0b10) != 0);
    const bool has_generator = (prefix & 1) != 0;

    if (block.version == 0) {
        if (has_generator) {
            block.transactions_generator = Program::parse(r);
        }
        block.transactions_generator_ref_list =
            parse_list<uint32_t>(r, [](streamable::Reader& reader) { return reader.read_u32_be(); });
    } else if (block.version == 1) {
        if (has_generator) {
            block.transactions_generator_buffer = r.read_bytes();
        }
    } else {
        throw streamable::ParseError("invalid full block version");
    }

    if (r.remaining() != 0) {
        throw streamable::ParseError("trailing bytes in full block");
    }
    return block;
}

std::vector<uint8_t> FullBlock::to_bytes() const {
    streamable::Writer w;
    stream_list<EndOfSubSlotBundle>(w, finished_sub_slots);
    reward_chain_block.stream(w);
    stream_optional<VDFProof>(w, challenge_chain_sp_proof);
    challenge_chain_ip_proof.stream(w);
    stream_optional<VDFProof>(w, reward_chain_sp_proof);
    reward_chain_ip_proof.stream(w);
    stream_optional<VDFProof>(w, infused_challenge_chain_ip_proof);
    foliage.stream(w);
    stream_optional<FoliageTransactionBlock>(w, foliage_transaction_block);
    stream_optional<TransactionsInfo>(w, transactions_info);

    if (version == 0) {
        uint8_t prefix = 0;
        if (transactions_generator.has_value()) {
            prefix |= 1;
        }
        w.write_u8(prefix);
        if (transactions_generator.has_value()) {
            transactions_generator->stream(w);
        }
        stream_list(w, transactions_generator_ref_list, [](streamable::Writer& writer, uint32_t value) { writer.write_u32_be(value); });
    } else if (version == 1) {
        if (transactions_generator_buffer.has_value()) {
            w.write_u8(0b11);
            w.write_bytes(*transactions_generator_buffer);
        } else {
            w.write_u8(0b10);
        }
    } else {
        throw streamable::ParseError("invalid full block version");
    }
    return w.take();
}

bool FullBlock::is_fully_compactified() const {
    for (const auto& sub_slot : finished_sub_slots) {
        if (!proof_is_compact(sub_slot.proofs.challenge_chain_slot_proof)) {
            return false;
        }
        if (sub_slot.proofs.infused_challenge_chain_slot_proof.has_value() &&
            !proof_is_compact(*sub_slot.proofs.infused_challenge_chain_slot_proof)) {
            return false;
        }
    }
    if (challenge_chain_sp_proof.has_value() && !proof_is_compact(*challenge_chain_sp_proof)) {
        return false;
    }
    return proof_is_compact(challenge_chain_ip_proof);
}

Bytes32 FullBlock::header_hash() const {
    // For DB lookup we use the foliage hash stored in the DB key; recomputing the
    // hash requires BLS and tree hashing. Callers should use the header hash from
    // compactvdf entries and DB keys instead of this placeholder.
    return foliage.reward_block_hash;
}

uint32_t FullBlock::height() const { return reward_chain_block.height; }

namespace {

void maybe_add_witness_type_zero_entry(const chia::Bytes32& header_hash, uint8_t field_vdf, const VDFProof& proof,
                                       std::optional<uint8_t> sub_slot_index, std::vector<CompactVdfEntry>& out) {
    if (!proof_is_compact(proof) || proof.witness.empty()) {
        return;
    }
    CompactVdfEntry entry;
    entry.header_hash = header_hash;
    entry.field_vdf = field_vdf;
    entry.witness = proof.witness;
    entry.sub_slot_index = sub_slot_index;
    out.push_back(std::move(entry));
}

}  // namespace

std::vector<CompactVdfEntry> extract_witness_type_zero_entries(const chia::Bytes32& header_hash,
                                                               const FullBlock& block) {
    std::vector<CompactVdfEntry> entries;
    for (std::size_t sub_slot_index = 0; sub_slot_index < block.finished_sub_slots.size(); ++sub_slot_index) {
        const auto& sub_slot = block.finished_sub_slots[sub_slot_index];
        const auto index = static_cast<uint8_t>(sub_slot_index);
        maybe_add_witness_type_zero_entry(header_hash, static_cast<uint8_t>(CompressibleVDFField::CC_EOS_VDF),
                                          sub_slot.proofs.challenge_chain_slot_proof, index, entries);
        if (sub_slot.proofs.infused_challenge_chain_slot_proof.has_value()) {
            maybe_add_witness_type_zero_entry(header_hash, static_cast<uint8_t>(CompressibleVDFField::ICC_EOS_VDF),
                                              *sub_slot.proofs.infused_challenge_chain_slot_proof, index, entries);
        }
    }
    if (block.challenge_chain_sp_proof.has_value()) {
        maybe_add_witness_type_zero_entry(header_hash, static_cast<uint8_t>(CompressibleVDFField::CC_SP_VDF),
                                          *block.challenge_chain_sp_proof, std::nullopt, entries);
    }
    maybe_add_witness_type_zero_entry(header_hash, static_cast<uint8_t>(CompressibleVDFField::CC_IP_VDF),
                                      block.challenge_chain_ip_proof, std::nullopt, entries);
    return entries;
}

std::vector<VDFInfo> vdf_info_candidates(const FullBlock& block, CompressibleVDFField field) {
    std::vector<VDFInfo> out;
    switch (field) {
        case CompressibleVDFField::CC_EOS_VDF:
            for (const auto& sub_slot : block.finished_sub_slots) {
                out.push_back(sub_slot.challenge_chain.challenge_chain_end_of_slot_vdf);
            }
            break;
        case CompressibleVDFField::ICC_EOS_VDF:
            for (const auto& sub_slot : block.finished_sub_slots) {
                if (sub_slot.infused_challenge_chain.has_value()) {
                    out.push_back(sub_slot.infused_challenge_chain->infused_challenge_chain_end_of_slot_vdf);
                }
            }
            break;
        case CompressibleVDFField::CC_SP_VDF:
            if (block.reward_chain_block.challenge_chain_sp_vdf.has_value()) {
                out.push_back(*block.reward_chain_block.challenge_chain_sp_vdf);
            }
            break;
        case CompressibleVDFField::CC_IP_VDF:
            out.push_back(block.reward_chain_block.challenge_chain_ip_vdf);
            break;
    }
    return out;
}

std::optional<VDFInfo> vdf_info_for_sub_slot(const FullBlock& block, CompressibleVDFField field,
                                             uint8_t sub_slot_index) {
    if (sub_slot_index >= block.finished_sub_slots.size()) {
        return std::nullopt;
    }
    const auto& sub_slot = block.finished_sub_slots[sub_slot_index];
    switch (field) {
        case CompressibleVDFField::CC_EOS_VDF:
            return sub_slot.challenge_chain.challenge_chain_end_of_slot_vdf;
        case CompressibleVDFField::ICC_EOS_VDF:
            if (!sub_slot.infused_challenge_chain.has_value()) {
                return std::nullopt;
            }
            return sub_slot.infused_challenge_chain->infused_challenge_chain_end_of_slot_vdf;
        case CompressibleVDFField::CC_SP_VDF:
        case CompressibleVDFField::CC_IP_VDF:
            return std::nullopt;
    }
    return std::nullopt;
}

bool block_field_needs_compact_proof(const FullBlock& block, CompressibleVDFField field,
                                       const std::optional<uint8_t>& sub_slot_index) {
    switch (field) {
        case CompressibleVDFField::CC_EOS_VDF:
            if (sub_slot_index.has_value()) {
                if (*sub_slot_index >= block.finished_sub_slots.size()) {
                    return false;
                }
                return !block.finished_sub_slots[*sub_slot_index].proofs.challenge_chain_slot_proof.is_compact();
            }
            for (const auto& sub_slot : block.finished_sub_slots) {
                if (!sub_slot.proofs.challenge_chain_slot_proof.is_compact()) {
                    return true;
                }
            }
            return false;
        case CompressibleVDFField::ICC_EOS_VDF:
            if (sub_slot_index.has_value()) {
                if (*sub_slot_index >= block.finished_sub_slots.size()) {
                    return false;
                }
                const auto& icc_proof = block.finished_sub_slots[*sub_slot_index].proofs.infused_challenge_chain_slot_proof;
                return icc_proof.has_value() && !icc_proof->is_compact();
            }
            for (const auto& sub_slot : block.finished_sub_slots) {
                const auto& icc_proof = sub_slot.proofs.infused_challenge_chain_slot_proof;
                if (icc_proof.has_value() && !icc_proof->is_compact()) {
                    return true;
                }
            }
            return false;
        case CompressibleVDFField::CC_SP_VDF:
            return block.challenge_chain_sp_proof.has_value() && !block.challenge_chain_sp_proof->is_compact();
        case CompressibleVDFField::CC_IP_VDF:
            return !block.challenge_chain_ip_proof.is_compact();
    }
    return false;
}

bool needs_compact_proof(const VDFInfo& info, const FullBlock& block, CompressibleVDFField field) {
    switch (field) {
        case CompressibleVDFField::CC_EOS_VDF:
            for (const auto& sub_slot : block.finished_sub_slots) {
                if (sub_slot.challenge_chain.challenge_chain_end_of_slot_vdf == info) {
                    return !proof_is_compact(sub_slot.proofs.challenge_chain_slot_proof);
                }
            }
            return false;
        case CompressibleVDFField::ICC_EOS_VDF:
            for (const auto& sub_slot : block.finished_sub_slots) {
                if (sub_slot.infused_challenge_chain.has_value() &&
                    sub_slot.infused_challenge_chain->infused_challenge_chain_end_of_slot_vdf == info) {
                    return sub_slot.proofs.infused_challenge_chain_slot_proof.has_value() &&
                           !proof_is_compact(*sub_slot.proofs.infused_challenge_chain_slot_proof);
                }
            }
            return false;
        case CompressibleVDFField::CC_SP_VDF:
            if (!block.reward_chain_block.challenge_chain_sp_vdf.has_value()) {
                return false;
            }
            if (*block.reward_chain_block.challenge_chain_sp_vdf != info) {
                return false;
            }
            return block.challenge_chain_sp_proof.has_value() && !proof_is_compact(*block.challenge_chain_sp_proof);
        case CompressibleVDFField::CC_IP_VDF:
            if (block.reward_chain_block.challenge_chain_ip_vdf != info) {
                return false;
            }
            return !proof_is_compact(block.challenge_chain_ip_proof);
    }
    return false;
}

bool apply_compact_proof(FullBlock& block, const VDFInfo& info, const VDFProof& proof, CompressibleVDFField field) {
    switch (field) {
        case CompressibleVDFField::CC_EOS_VDF:
            for (auto& sub_slot : block.finished_sub_slots) {
                if (sub_slot.challenge_chain.challenge_chain_end_of_slot_vdf == info) {
                    sub_slot.proofs.challenge_chain_slot_proof = proof;
                    return true;
                }
            }
            return false;
        case CompressibleVDFField::ICC_EOS_VDF:
            for (auto& sub_slot : block.finished_sub_slots) {
                if (sub_slot.infused_challenge_chain.has_value() &&
                    sub_slot.infused_challenge_chain->infused_challenge_chain_end_of_slot_vdf == info) {
                    sub_slot.proofs.infused_challenge_chain_slot_proof = proof;
                    return true;
                }
            }
            return false;
        case CompressibleVDFField::CC_SP_VDF:
            if (block.reward_chain_block.challenge_chain_sp_vdf.has_value() &&
                *block.reward_chain_block.challenge_chain_sp_vdf == info) {
                block.challenge_chain_sp_proof = proof;
                return true;
            }
            return false;
        case CompressibleVDFField::CC_IP_VDF:
            if (block.reward_chain_block.challenge_chain_ip_vdf == info) {
                block.challenge_chain_ip_proof = proof;
                return true;
            }
            return false;
    }
    return false;
}

std::vector<uint8_t> hex_to_bytes(const std::string& hex_in) {
    std::string hex = hex_in;
    if (hex.rfind("0x", 0) == 0 || hex.rfind("0X", 0) == 0) {
        hex = hex.substr(2);
    }
    if (hex.size() % 2 != 0) {
        throw std::invalid_argument("hex string must have even length");
    }
    std::vector<uint8_t> out;
    out.reserve(hex.size() / 2);
    for (size_t i = 0; i < hex.size(); i += 2) {
        const auto byte = std::stoul(hex.substr(i, 2), nullptr, 16);
        out.push_back(static_cast<uint8_t>(byte));
    }
    return out;
}

std::string bytes_to_hex(const uint8_t* data, size_t len) {
    static const char* kHex = "0123456789abcdef";
    std::string out;
    out.reserve(len * 2);
    for (size_t i = 0; i < len; ++i) {
        out.push_back(kHex[data[i] >> 4]);
        out.push_back(kHex[data[i] & 0x0f]);
    }
    return out;
}

std::string bytes32_to_db_hex(const Bytes32& hash) { return bytes_to_hex(hash.data(), hash.size()); }

std::size_t Bytes32Hash::operator()(const Bytes32& hash) const noexcept {
    std::size_t h = 0;
    for (const uint8_t byte : hash) {
        h = h * 31 + byte;
    }
    return h;
}

}  // namespace chia
