#include "vdf_validate.hpp"

#include "verifier.h"

#include <list>
#include <mutex>
#include <unordered_map>

namespace vdf {
namespace {

constexpr std::size_t kDiscriminantCacheSize = 200;

class DiscriminantCache {
  public:
    integer get(const chia::Bytes32& challenge) {
        std::lock_guard<std::mutex> lock(mutex_);
        const auto cached = entries_.find(challenge);
        if (cached != entries_.end()) {
            touch(challenge);
            return cached->second;
        }

        std::vector<uint8_t> seed(challenge.begin(), challenge.end());
        integer disc = CreateDiscriminant(seed, kDiscriminantSizeBits);
        insert(challenge, std::move(disc));
        return entries_.at(challenge);
    }

  private:
    void touch(const chia::Bytes32& challenge) {
        const auto it = lru_iters_.find(challenge);
        if (it != lru_iters_.end()) {
            lru_.splice(lru_.end(), lru_, it->second);
        }
    }

    void insert(const chia::Bytes32& challenge, integer disc) {
        if (entries_.size() >= kDiscriminantCacheSize && !lru_.empty()) {
            entries_.erase(lru_.front());
            lru_iters_.erase(lru_.front());
            lru_.pop_front();
        }
        entries_.emplace(challenge, std::move(disc));
        lru_.push_back(challenge);
        lru_iters_[challenge] = std::prev(lru_.end());
    }

    std::mutex mutex_;
    std::unordered_map<chia::Bytes32, integer, chia::Bytes32Hash> entries_;
    std::list<chia::Bytes32> lru_;
    std::unordered_map<chia::Bytes32, std::list<chia::Bytes32>::iterator, chia::Bytes32Hash> lru_iters_;
};

DiscriminantCache& discriminant_cache() {
    static DiscriminantCache cache;
    return cache;
}

integer discriminant_from_challenge(const chia::Bytes32& challenge) {
    return discriminant_cache().get(challenge);
}

}  // namespace

bool validate_vdf(const chia::VDFProof& proof, const chia::VDFInfo& info) {
    if (proof.witness_type > 64) {
        return false;
    }
    try {
        integer disc = discriminant_from_challenge(info.challenge);
        std::vector<uint8_t> proof_blob;
        proof_blob.insert(proof_blob.end(), info.output.begin(), info.output.end());
        proof_blob.insert(proof_blob.end(), proof.witness.begin(), proof.witness.end());

        const auto default_el = chia::ClassgroupElement::default_element();
        return CheckProofOfTimeNWesolowski(disc, default_el.data.data(), proof_blob.data(), proof_blob.size(),
                                           info.number_of_iterations, kDiscriminantSizeBits, proof.witness_type);
    } catch (...) {
        return false;
    }
}

std::optional<chia::VDFInfo> find_vdf_info_for_proof(const chia::FullBlock& block, chia::CompressibleVDFField field,
                                                     const chia::VDFProof& proof) {
    for (const auto& candidate : chia::vdf_info_candidates(block, field)) {
        if (validate_vdf(proof, candidate)) {
            return candidate;
        }
    }
    return std::nullopt;
}

std::optional<chia::VDFInfo> find_vdf_info_for_entry(const chia::FullBlock& block, chia::CompressibleVDFField field,
                                                     const chia::VDFProof& proof,
                                                     const std::optional<uint8_t>& sub_slot_index) {
    (void)proof;
    if (sub_slot_index.has_value()) {
        return chia::vdf_info_for_sub_slot(block, field, *sub_slot_index);
    }
    return find_vdf_info_for_proof(block, field, proof);
}

}  // namespace vdf
