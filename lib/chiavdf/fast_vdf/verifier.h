#include "include.h"
#include "integer_common.h"
#include "vdf_new.h"
#include "picosha2.h"
#include "nucomp.h"
#include "proof_common.h"
#include "create_discriminant.h"

void VerifyWesolowskiProof(integer &D, form x, form y, form proof, uint64_t iters, bool &is_valid)
{
    PulmarkReducer reducer;
    int int_size = (D.num_bits() + 16) >> 4;
    integer L = root(-D, 4);
    integer B = GetB(D, x, y);
    integer r = FastPow(2, iters, B);
    form f1 = FastPowFormNucomp(proof, D, B, L, reducer);
    form f2 = FastPowFormNucomp(x, D, r, L, reducer);
    if (f1 * f2 == y)
    {
        is_valid = true;
    }
    else
    {
        is_valid = false;
    }
}

integer ConvertBytesToInt(uint8_t *bytes, int start_index, int end_index)
{
    integer res(0);
    bool negative = false;
    if (bytes[start_index] & (1 << 7))
        negative = true;
    for (int i = start_index; i < end_index; i++)
    {
        res = res * integer(256);
        if (!negative)
            res = res + integer(bytes[i]);
        else
            res = res + integer(bytes[i] ^ 255);
    }
    if (negative)
    {
        res = res + integer(1);
        res = res * integer(-1);
    }
    return res;
}

form DeserializeForm(integer &d, uint8_t *bytes, int int_size)
{
    integer a = ConvertBytesToInt(bytes, 0, int_size);
    integer b = ConvertBytesToInt(bytes, int_size, 2 * int_size);    
    form f = form::from_abd(a, b, d);
    return f;
}

std::vector<form> DeserializeProof(uint8_t *proof_bytes, int proof_len, integer &D)
{
    int int_size = (D.num_bits() + 16) >> 4;
    std::vector<form> proof;
    for (int i = 0; i < proof_len; i += 2 * int_size)
    {
        std::vector<uint8_t> tmp_bytes;
        for (int j = 0; j < 2 * int_size; j++)
            tmp_bytes.push_back(proof_bytes[i + j]);
        proof.emplace_back(DeserializeForm(D, tmp_bytes.data(), int_size));
    }
    return proof;
}

bool CheckProofOfTimeNWesolowskiInner(integer &D, form x, uint8_t *proof_blob,
                                      int blob_len, int iters, int int_size,
                                      std::vector<int> iter_list, int recursion)
{
    uint8_t* result_bytes = new uint8_t[2 * int_size];
    uint8_t* proof_bytes = new uint8_t[blob_len - 2 * int_size];
    memcpy(result_bytes, proof_blob, 2 * int_size);
    memcpy(proof_bytes, proof_blob + 2 * int_size, blob_len - 2 * int_size);
    form y = DeserializeForm(D, result_bytes, int_size);
    std::vector<form> proof = DeserializeProof(proof_bytes, blob_len - 2 * int_size, D);
    if (recursion * 2 + 1 != proof.size())
        return false;
    if (proof.size() == 1)
    {
        bool is_valid;
        VerifyWesolowskiProof(D, x, y, proof[0], iters, is_valid);
        delete[] result_bytes;
        delete[] proof_bytes;
        return is_valid;
    }
    else
    {
        if (!(proof.size() % 2 == 1 && proof.size() > 2)) {
            delete[] result_bytes;
            delete[] proof_bytes;
            return false;
        }
        int iters1 = iter_list[iter_list.size() - 1];
        int iters2 = iters - iters1;
        bool ver_outer;
        VerifyWesolowskiProof(D, x, proof[proof.size() - 2], proof[proof.size() - 1], iters1, ver_outer);
        if (!ver_outer) {
            delete[] result_bytes;
            delete[] proof_bytes;
            return false;
        }
        uint8_t* new_proof_bytes = new uint8_t[blob_len - 4 * int_size];
        for (int i = 0; i < blob_len - 4 * int_size; i++)
            new_proof_bytes[i] = proof_blob[i];
        iter_list.pop_back();
        bool ver_inner = CheckProofOfTimeNWesolowskiInner(D, proof[proof.size() - 2], new_proof_bytes, blob_len - 4 * int_size, iters2, int_size, iter_list, recursion - 1);
        delete[] result_bytes;
        delete[] proof_bytes;
        delete[] new_proof_bytes;
        if (ver_inner)
            return true;
        return false;
    }
}

bool CheckProofOfTimeNWesolowski(integer D, form x, uint8_t *proof_blob, int proof_blob_len, int iters, int recursion)
{
    int int_size = (D.num_bits() + 16) >> 4;
    uint8_t* new_proof_blob = new uint8_t[proof_blob_len];
    int new_cnt = 4 * int_size;
    memcpy(new_proof_blob, proof_blob, new_cnt);
    std::vector<int> iter_list;
    for (int i = new_cnt; i < proof_blob_len; i += 4 * int_size + 8)
    {
        auto iter_vector = ConvertBytesToInt(proof_blob, i, i + 8).to_vector();
        iter_list.push_back(iter_vector[0]);
        if (iter_vector[0] < 0)
            return false;
        memcpy(new_proof_blob + new_cnt, proof_blob + i + 8, 4 * int_size);
        new_cnt += 4 * int_size;
    }
    bool is_valid = CheckProofOfTimeNWesolowskiInner(D, x, new_proof_blob, new_cnt, iters, int_size, iter_list, recursion);
    delete[] new_proof_blob;
    return is_valid; 
}

std::vector<uint8_t> HexToBytes(char *hex_proof)
{
    int len = strlen(hex_proof);
    assert(len % 2 == 0);
    std::vector<uint8_t> result;
    for (int i = 0; i < len; i += 2)
    {
        int hex1 = hex_proof[i] >= 'a' ? (hex_proof[i] - 'a' + 10) : (hex_proof[i] - '0');
        int hex2 = hex_proof[i + 1] >= 'a' ? (hex_proof[i + 1] - 'a' + 10) : (hex_proof[i + 1] - '0');
        result.push_back(hex1 * 16 + hex2);
    }
    return result;
}

// Intended to match with ProofOfTime type from Chia Blockchain.
struct ProofOfTimeType
{
    int discriminant_size_bits;
    std::vector<uint8_t> challenge_hash;
    integer a;
    integer b;
    uint64_t iterations_needed;
    std::vector<uint8_t> witness;
    uint8_t witness_type;

    ProofOfTimeType(const int discriminant_size_bits, const std::vector<uint8_t>& challenge_hash, const integer &a, const integer &b, uint64_t iterations_needed,
                    const std::vector<uint8_t> &witness, uint8_t witness_type)
    {
        this->discriminant_size_bits = discriminant_size_bits;
        this->challenge_hash = challenge_hash;
        this->a = a;
        this->b = b;
        this->iterations_needed = iterations_needed;
        this->witness = witness;
        this->witness_type = witness_type;
    }
};

// Converts from ProofOfTimeType to CheckProofOfTimeNWesolowski-like arguments and calls the check.
bool CheckProofOfTimeType(ProofOfTimeType &proof)
{
    bool result;
    integer discriminant = CreateDiscriminant(proof.challenge_hash, proof.discriminant_size_bits);

    try
    {
        form x = form::generator(discriminant);
        int int_size = (discriminant.num_bits() + 16) >> 4;
        form y = form::from_abd(proof.a, proof.b, discriminant);
        std::vector<uint8_t> proof_blob = SerializeForm(y, int_size);
        proof_blob.insert(proof_blob.end(), proof.witness.begin(), proof.witness.end());
        result = CheckProofOfTimeNWesolowski(discriminant, x, proof_blob.data(), proof_blob.size(), proof.iterations_needed, proof.witness_type);
    }
    catch (std::exception &e)
    {
        result = false;
    }
    return result;
}
