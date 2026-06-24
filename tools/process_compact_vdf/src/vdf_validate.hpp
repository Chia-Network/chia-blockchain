#pragma once

#include "chia_protocol.hpp"

#include <cstdint>
#include <optional>

namespace vdf {

constexpr uint16_t kDiscriminantSizeBits = 1024;

bool validate_vdf(const chia::VDFProof& proof, const chia::VDFInfo& info);

std::optional<chia::VDFInfo> find_vdf_info_for_proof(const chia::FullBlock& block, chia::CompressibleVDFField field,
                                                     const chia::VDFProof& proof);

}  // namespace vdf
