#include <pybind11/pybind11.h>
#include "../verifier.h"

namespace py = pybind11;

PYBIND11_MODULE(chiavdf, m) {
    m.doc() = "Chia proof of time";

    m.def("verify", [] (int discriminant_size_bits, const py::bytes& challenge_hash, const string& a, 
                        const string& b, uint64_t num_iterations, const py::bytes& witness,
                        uint8_t witness_type) {
        std::string challenge_hash_str(challenge_hash);
        std::string witness_str(witness);
        ProofOfTimeType pot(
            discriminant_size_bits,
            std::vector<uint8_t>(challenge_hash_str.begin(), challenge_hash_str.end()),
            integer(a),
            integer(b),
            num_iterations,
            std::vector<uint8_t>(witness_str.begin(), witness_str.end()),
            witness_type
        );
        return CheckProofOfTimeType(pot);
    });
}
