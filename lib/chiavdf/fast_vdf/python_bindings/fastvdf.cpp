#include <pybind11/pybind11.h>
#include "../verifier.h"
#include "../prover_slow.h"

namespace py = pybind11;

PYBIND11_MODULE(fastvdf, m) {
    m.doc() = "Chia proof of time";

    // Checks a ProofOFTime type by pybinding everything to C++. Currently deprecated.
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

    // Creates discriminant.
    m.def("create_discriminant", [] (const py::bytes& challenge_hash, int discriminant_size_bits) {
        std::string challenge_hash_str(challenge_hash);
        auto challenge_hash_bits = std::vector<uint8_t>(challenge_hash_str.begin(), challenge_hash_str.end());
        integer D = CreateDiscriminant(
            challenge_hash_bits,
            discriminant_size_bits
        );
        return D.to_string();
    });

    // Checks a simple wesolowski proof.
    m.def("verify_wesolowski", [] (const string& discriminant,
                                   const string& x_a, const string& x_b,
                                   const string& y_a, const string& y_b,
                                   const string& proof_a, const string& proof_b,
                                   uint64_t num_iterations) {
        integer D(discriminant);
        form x = form::from_abd(
            integer(x_a),
            integer(x_b),
            D
        );
        form y = form::from_abd(
            integer(y_a),
            integer(y_b),
            D
        );
        form proof = form::from_abd(
            integer(proof_a),
            integer(proof_b),
            D
        );
        bool is_valid = false;
        VerifyWesolowskiProof(D, x, y, proof, num_iterations, is_valid);
        return is_valid;
    });

    m.def("prove", [] (const py::bytes& challenge_hash, int discriminant_size_bits, uint64_t num_iterations) {
        std::string challenge_hash_str(challenge_hash);
        std::vector<uint8_t> challenge_hash_bytes(challenge_hash_str.begin(), challenge_hash_str.end());
        auto result = ProveSlow(challenge_hash_bytes, discriminant_size_bits, num_iterations);
        py::bytes ret = py::bytes(reinterpret_cast<char*>(result.data()), result.size());
        return ret;
    });
}
