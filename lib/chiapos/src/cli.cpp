// Copyright 2018 Chia Network Inc

// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at

//    http://www.apache.org/licenses/LICENSE-2.0

// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

#include <set>
#include <ctime>

#include "../lib/include/picosha2.hpp"
#include "../lib/include/cxxopts.hpp"

#include "plotter_disk.hpp"
#include "prover_disk.hpp"
#include "verifier.hpp"

void HexToBytes(const string& hex, uint8_t* result) {
    for (uint32_t i = 0; i < hex.length(); i += 2) {
        string byteString = hex.substr(i, 2);
        uint8_t byte = (uint8_t) strtol(byteString.c_str(), NULL, 16);
        result[i/2] = byte;
  }
}

vector<unsigned char> intToBytes(uint32_t paramInt, uint32_t numBytes) {
    vector<unsigned char> arrayOfByte(numBytes, 0);
    for (uint32_t i = 0; paramInt > 0; i++) {
        arrayOfByte[numBytes - i - 1] = paramInt & 0xff;
        paramInt >>= 8;
    }
    return arrayOfByte;
}

string Strip0x(const string& hex) {
    if (hex.substr(0, 2) == "0x" || hex.substr(0, 2) == "0X") {
        return hex.substr(2);
    }
    return hex;
}

void HelpAndQuit(cxxopts::Options options) {
    cout << options.help({""}) << endl;
    cout << "./ProofOfSpace generate" << endl;
    cout << "./ProofOfSpace prove <challenge>" << endl;
    cout << "./ProofOfSpace verify <challenge> <proof>" << endl;
    cout << "./ProofOfSpace check" << endl;
    exit(0);
}

int main(int argc, char *argv[]) {
    try {
        cxxopts::Options options("ProofOfSpace", "Utility for plotting, generating and verifying proofs of space.");
        options.positional_help("(generate/prove/verify/check) param1 param2 ")
               .show_positional_help();

        // Default values
        uint8_t k = 20;
        string filename = "plot.dat";
        string tempdir = ".";
        string finaldir = ".";
        string operation = "help";
        string memo  = "0102030405";
        string id = "022fb42c08c12de3a6af053880199806532e79515f94e83461612101f9412f9e";

        options.allow_unrecognised_options()
               .add_options()
                ("k, size", "Plot size", cxxopts::value<uint8_t>(k))
                ("t, tempdir", "Temporary directory", cxxopts::value<string>(tempdir))
                ("d, finaldir", "Final directory", cxxopts::value<string>(finaldir))
                ("f, file", "Filename", cxxopts::value<string>(filename))
                ("m, memo", "Memo to insert into the plot", cxxopts::value<string>(memo))
                ("i, id", "Unique 32-byte seed for the plot", cxxopts::value<string>(id))
                ("help", "Print help");

        auto result = options.parse(argc, argv);

        if (result.count("help") || argc < 2) {
            HelpAndQuit(options);
        }
        operation = argv[1];
        std::cout << "operation" << operation << std::endl;

        if (operation == "help") {
            HelpAndQuit(options);
        } else if (operation == "generate") {
            cout << "Generating plot for k=" << static_cast<int>(k) << " filename="
                 << filename << " id=" << id << endl << endl;
            if (id.size() != 64) {
                cout << "Invalid ID, should be 32 bytes" << endl;
                exit(1);
            }
            memo = Strip0x(memo);
            id = Strip0x(id);
            uint8_t memo_bytes[memo.size() / 2];
            uint8_t id_bytes[32];

            HexToBytes(memo, memo_bytes);
            HexToBytes(id, id_bytes);

            DiskPlotter plotter = DiskPlotter();
            plotter.CreatePlotDisk(tempdir, finaldir, filename, k, memo_bytes, 5, id_bytes, 32);
        } else if (operation == "prove") {
            if (argc < 3) {
                HelpAndQuit(options);
            }
            cout << "Proving using filename=" << filename << " challenge=" << argv[2] << endl << endl;
            string challenge = Strip0x(argv[2]);
            if (challenge.size() != 64) {
                cout << "Invalid challenge, should be 32 bytes" << endl;
                exit(1);
            }
            uint8_t challenge_bytes[32];
            HexToBytes(challenge, challenge_bytes);

            DiskProver prover(filename);
            vector<LargeBits> qualities = prover.GetQualitiesForChallenge(challenge_bytes);
            for (uint32_t i = 0; i < qualities.size(); i++) {
                k = prover.GetSize() / 2;
                uint8_t proof_data[8 * k];
                LargeBits proof = prover.GetFullProof(challenge_bytes, i);
                proof.ToBytes(proof_data);
                cout << "Proof: 0x" << Util::HexStr(proof_data, k * 8) << endl;
            }
            if (qualities.empty()) {
                cout << "No proofs found." << endl;
                exit(1);
            }
        } else if (operation == "verify") {
            if (argc < 4) {
                HelpAndQuit(options);
            }
            cout << "Verifying proof=" << argv[2] << " for challenge=" << argv[3] << " and k="
                 << static_cast<int>(k) << endl << endl;
            Verifier verifier = Verifier();

            id = Strip0x(id);
            string proof = Strip0x(argv[2]);
            string challenge = Strip0x(argv[3]);
            if (id.size() != 64) {
                cout << "Invalid ID, should be 32 bytes" << endl;
                exit(1);
            }
            if (challenge.size() != 64) {
                cout << "Invalid challenge, should be 32 bytes" << endl;
                exit(1);
            }
            uint8_t id_bytes[32];
            uint8_t challenge_bytes[32];
            uint8_t proof_bytes[proof.size() / 2];
            HexToBytes(id, id_bytes);
            HexToBytes(challenge, challenge_bytes);
            HexToBytes(proof, proof_bytes);

            LargeBits quality = verifier.ValidateProof(id_bytes, k, challenge_bytes, proof_bytes, k*8);
            if (quality.GetSize() == 2*k) {
                cout << "Proof verification suceeded. Quality: " << quality << endl;
            } else {
                cout << "Proof verification failed." << endl;
                exit(1);
            }
        } else if (operation == "check") {
            uint32_t iterations = 1000;
            if (argc == 3) {
                iterations = stoi(argv[2]);
            }

            DiskProver prover(filename);
            Verifier verifier = Verifier();

            uint32_t success = 0;
            id = Strip0x(id);
            uint8_t id_bytes[32];
            HexToBytes(id, id_bytes);

            for (uint32_t num = 0; num < iterations; num++) {
                vector<unsigned char> hash_input = intToBytes(num, 4);
                hash_input.insert(hash_input.end(),&id_bytes[0],&id_bytes[32]);

                vector<unsigned char> hash(picosha2::k_digest_size);
                picosha2::hash256(hash_input.begin(), hash_input.end(), hash.begin(), hash.end());

                vector<LargeBits> qualities = prover.GetQualitiesForChallenge(hash.data());
                for (uint32_t i = 0; i < qualities.size(); i++) {
                    k = qualities[i].GetSize() / 2;
                    LargeBits proof = prover.GetFullProof(hash.data(), i);
                    uint8_t proof_data[proof.GetSize() / 8];
                    proof.ToBytes(proof_data);
                    cout << "i: " << num << std::endl;
                    cout << "chalenge: 0x" << Util::HexStr(hash.data(), 256 / 8) << endl;
                    cout << "proof: 0x" << Util::HexStr(proof_data, k * 8) << endl;
                    LargeBits quality = verifier.ValidateProof(id_bytes, k, hash.data(), proof_data, k*8);
                    if (quality.GetSize() == 2*k) {
                        cout << "quality: " << quality << endl;
                        cout << "Proof verification suceeded. k = " << static_cast<int>(k) << endl;
                        success++;
                    } else {
                        cout << "Proof verification failed." << endl;
                        exit(1);
                    }
                }
            }
            std::cout << "Total success: " << success << "/" << iterations << ", " <<
                         (success/static_cast<double>(iterations)) << "%." << std::endl;
        } else {
            cout << "Invalid operation. Use generate/prove/verify/check" << endl;
        }
        exit(0);
    } catch (const cxxopts::OptionException& e) {
        cout << "error parsing options: " << e.what() << endl;
        exit(1);
    }
}
