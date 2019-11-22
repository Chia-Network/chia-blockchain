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
//
// Some public domain code is taken from pycrypto:
// https://github.com/dlitz/pycrypto/blob/master/src/AESNI.c
//
//  AESNI.c: AES using AES-NI instructions
//
// Written in 2013 by Sebastian Ramacher <sebastian@ramacher.at>

#ifndef SRC_CPP_AES_HPP_
#define SRC_CPP_AES_HPP_

#include <string.h>    // for memcmp
#include <wmmintrin.h>   // for intrinsics for AES-NI

/**
 *  Encrypts a message of 128 bits with a 128 bit key, using
 *  10 rounds of AES128 (9 full rounds and one final round). Uses AES-NI
 *  assembly instructions.
 */
#define DO_ENC_BLOCK_128(m, k)              \
    do                                      \
    {                                       \
        m = _mm_xor_si128(m, k[0]);         \
        m = _mm_aesenc_si128(m, k[1]);      \
        m = _mm_aesenc_si128(m, k[2]);      \
        m = _mm_aesenc_si128(m, k[3]);      \
        m = _mm_aesenc_si128(m, k[4]);      \
        m = _mm_aesenc_si128(m, k[5]);      \
        m = _mm_aesenc_si128(m, k[6]);      \
        m = _mm_aesenc_si128(m, k[7]);      \
        m = _mm_aesenc_si128(m, k[8]);      \
        m = _mm_aesenc_si128(m, k[9]);      \
        m = _mm_aesenclast_si128(m, k[10]); \
    } while (0)

/**
 *  Encrypts a message of 128 bits with a 256 bit key, using
 *  13 rounds of AES256 (13 full rounds and one final round). Uses
 *  AES-NI assembly instructions.
 */
#define DO_ENC_BLOCK_256(m, k) \
    do {\
        m = _mm_xor_si128(m, k[ 0]); \
        m = _mm_aesenc_si128(m, k[ 1]); \
        m = _mm_aesenc_si128(m, k[ 2]); \
        m = _mm_aesenc_si128(m, k[ 3]); \
        m = _mm_aesenc_si128(m, k[ 4]); \
        m = _mm_aesenc_si128(m, k[ 5]); \
        m = _mm_aesenc_si128(m, k[ 6]); \
        m = _mm_aesenc_si128(m, k[ 7]); \
        m = _mm_aesenc_si128(m, k[ 8]); \
        m = _mm_aesenc_si128(m, k[ 9]); \
        m = _mm_aesenc_si128(m, k[ 10]);\
        m = _mm_aesenc_si128(m, k[ 11]);\
        m = _mm_aesenc_si128(m, k[ 12]);\
        m = _mm_aesenc_si128(m, k[ 13]);\
        m = _mm_aesenclast_si128(m, k[ 14]);\
    }while(0)

/**
 * Encrypts a message of 128 bits with a 128 bit key, using
 * 2 full rounds of AES128. Uses AES-NI assembly instructions.
 */
#define DO_ENC_BLOCK_2ROUND(m, k)      \
    do                                 \
    {                                  \
        m = _mm_xor_si128(m, k[0]);    \
        m = _mm_aesenc_si128(m, k[1]); \
        m = _mm_aesenc_si128(m, k[2]); \
    } while (0)
/**
 * Decrypts a ciphertext of 128 bits with a 128 bit key, using
 * 10 rounds of AES128 (9 full rounds and one final round).
 * Uses AES-NI assembly instructions.
 */
#define DO_DEC_BLOCK(m, k)                  \
    do                                      \
    {                                       \
        m = _mm_xor_si128(m, k[10 + 0]);    \
        m = _mm_aesdec_si128(m, k[10 + 1]); \
        m = _mm_aesdec_si128(m, k[10 + 2]); \
        m = _mm_aesdec_si128(m, k[10 + 3]); \
        m = _mm_aesdec_si128(m, k[10 + 4]); \
        m = _mm_aesdec_si128(m, k[10 + 5]); \
        m = _mm_aesdec_si128(m, k[10 + 6]); \
        m = _mm_aesdec_si128(m, k[10 + 7]); \
        m = _mm_aesdec_si128(m, k[10 + 8]); \
        m = _mm_aesdec_si128(m, k[10 + 9]); \
        m = _mm_aesdeclast_si128(m, k[0]);  \
    } while (0)

/**
 * Decrypts a ciphertext of 128 bits with a 128 bit key, using
 * 2 full rounds of AES128. Uses AES-NI assembly instructions.
 * Will not work unless key schedule is modified.
 */
/*
#define DO_DEC_BLOCK_2ROUND(m, k)           \
    do                                      \
    {                                       \
        m = _mm_xor_si128(m, k[2 + 0]);    \
        m = _mm_aesdec_si128(m, k[2 + 1]); \
        m = _mm_aesdec_si128(m, k[2 + 2]); \
    } while (0)
*/

static __m128i key_schedule[20];  // The expanded key

static __m128i aes128_keyexpand(__m128i key) {
    key = _mm_xor_si128(key, _mm_slli_si128(key, 4));
    key = _mm_xor_si128(key, _mm_slli_si128(key, 4));
    return _mm_xor_si128(key, _mm_slli_si128(key, 4));
}

#define KEYEXP128_H(K1, K2, I, S) _mm_xor_si128(aes128_keyexpand(K1), \
        _mm_shuffle_epi32(_mm_aeskeygenassist_si128(K2, I), S))

#define KEYEXP128(K, I) KEYEXP128_H(K, K, I, 0xff)
#define KEYEXP256(K1, K2, I)  KEYEXP128_H(K1, K2, I, 0xff)
#define KEYEXP256_2(K1, K2) KEYEXP128_H(K1, K2, 0x00, 0xaa)

// public API

/*
 * Loads an AES key. Can either be a 16 byte or 32 byte bytearray.
 */
void aes_load_key(uint8_t *enc_key, int keylen) {
    switch (keylen) {
        case 16: {
            /* 128 bit key setup */
            key_schedule[0] = _mm_loadu_si128((const __m128i*) enc_key);
            key_schedule[1] = KEYEXP128(key_schedule[0], 0x01);
            key_schedule[2] = KEYEXP128(key_schedule[1], 0x02);
            key_schedule[3] = KEYEXP128(key_schedule[2], 0x04);
            key_schedule[4] = KEYEXP128(key_schedule[3], 0x08);
            key_schedule[5] = KEYEXP128(key_schedule[4], 0x10);
            key_schedule[6] = KEYEXP128(key_schedule[5], 0x20);
            key_schedule[7] = KEYEXP128(key_schedule[6], 0x40);
            key_schedule[8] = KEYEXP128(key_schedule[7], 0x80);
            key_schedule[9] = KEYEXP128(key_schedule[8], 0x1B);
            key_schedule[10] = KEYEXP128(key_schedule[9], 0x36);
            break;
        }
        case 32: {
            /* 256 bit key setup */
            key_schedule[0] = _mm_loadu_si128((const __m128i*) enc_key);
            key_schedule[1] = _mm_loadu_si128((const __m128i*) (enc_key+16));
            key_schedule[2] = KEYEXP256(key_schedule[0], key_schedule[1], 0x01);
            key_schedule[3] = KEYEXP256_2(key_schedule[1], key_schedule[2]);
            key_schedule[4] = KEYEXP256(key_schedule[2], key_schedule[3], 0x02);
            key_schedule[5] = KEYEXP256_2(key_schedule[3], key_schedule[4]);
            key_schedule[6] = KEYEXP256(key_schedule[4], key_schedule[5], 0x04);
            key_schedule[7] = KEYEXP256_2(key_schedule[5], key_schedule[6]);
            key_schedule[8] = KEYEXP256(key_schedule[6], key_schedule[7], 0x08);
            key_schedule[9] = KEYEXP256_2(key_schedule[7], key_schedule[8]);
            key_schedule[10] = KEYEXP256(key_schedule[8], key_schedule[9], 0x10);
            key_schedule[11] = KEYEXP256_2(key_schedule[9], key_schedule[10]);
            key_schedule[12] = KEYEXP256(key_schedule[10], key_schedule[11], 0x20);
            key_schedule[13] = KEYEXP256_2(key_schedule[11], key_schedule[12]);
            key_schedule[14] = KEYEXP256(key_schedule[12], key_schedule[13], 0x40);
            break;
        }
    }
}

// Declares a global variable for efficiency.
__m128i m_global;

/*
 * Encrypts a plaintext using AES256.
 */
static inline void aes256_enc(const uint8_t *plainText, uint8_t *cipherText) {
    m_global = _mm_loadu_si128(reinterpret_cast<const __m128i *>(plainText));

    DO_ENC_BLOCK_256(m_global, key_schedule);

    _mm_storeu_si128(reinterpret_cast<__m128i *>(cipherText), m_global);
}

/*
 * Encrypts a plaintext using AES128 with 2 rounds.
 */
static inline void aes128_enc(const uint8_t *plainText, uint8_t *cipherText) {
    m_global = _mm_loadu_si128(reinterpret_cast<const __m128i *>(plainText));

    // Uses the 2 round encryption innstead of the full 10 round encryption
    DO_ENC_BLOCK_2ROUND(m_global, key_schedule);

    _mm_storeu_si128(reinterpret_cast<__m128i *>(cipherText), m_global);
}

/*
 * Encrypts an integer using AES128 with 2 rounds.
 */
static inline __m128i aes128_enc_int(__m128i plainText) {
    // Uses the 2 round encryption innstead of the full 10 round encryption
    DO_ENC_BLOCK_2ROUND(plainText, key_schedule);
    return plainText;
}

__m128i m1;
__m128i m2;
__m128i m3;
__m128i m4;

/*
 * Uses AES cache mode to map a 2 block ciphertext into 128 bit result.
 */
static inline void aes128_2b(uint8_t *block1, uint8_t *block2, uint8_t *res) {
    m1 = _mm_loadu_si128(reinterpret_cast<__m128i *>(block1));
    m2 = _mm_loadu_si128(reinterpret_cast<__m128i *>(block2));
    m3 = aes128_enc_int(m1);  // E(L)
    m3 = aes128_enc_int(_mm_xor_si128(m3, m2));
    _mm_storeu_si128(reinterpret_cast<__m128i *>(res), m3);
}

/*
 * Uses AES cache mode to map a 3 block ciphertext into 128 bit result.
 */
static inline void aes128_3b(uint8_t *block1, uint8_t* block2, uint8_t *block3, uint8_t* res) {
    m1 = _mm_loadu_si128(reinterpret_cast<__m128i *>(block1));
    m2 = _mm_loadu_si128(reinterpret_cast<__m128i *>(block2));

    m1 = aes128_enc_int(m1);  // E(La)
    m2 = aes128_enc_int(m2);  // E(Ra)

    m1 = _mm_xor_si128(m1, m2);
    m2 = _mm_loadu_si128(reinterpret_cast<__m128i *>(block3));

    m2 = aes128_enc_int(m2);
    m1 = _mm_xor_si128(m1, m2);
    m3 = aes128_enc_int(m1);
    _mm_storeu_si128(reinterpret_cast<__m128i *>(res), m3);
}

/*
 * Uses AES cache mode to map a 4 block ciphertext into 128 bit result.
 */
static inline void aes128_4b(uint8_t *block1, uint8_t* block2, uint8_t *block3, uint8_t* block4, uint8_t* res) {
    m1 = _mm_loadu_si128(reinterpret_cast<__m128i *>(block1));
    m2 = _mm_loadu_si128(reinterpret_cast<__m128i *>(block3));
    m3 = _mm_loadu_si128(reinterpret_cast<__m128i *>(block2));
    m4 = _mm_loadu_si128(reinterpret_cast<__m128i *>(block4));

    m1 = aes128_enc_int(m1);    // E(La)
    m1 = _mm_xor_si128(m1, m3);
    m1 = aes128_enc_int(m1);    // E(E(La) ^ Lb)
    m2 = aes128_enc_int(m2);    // E(Ra)

    m1 = _mm_xor_si128(m1, m2);  // xor e(Ra)
    m1 = _mm_xor_si128(m1, m4);  // xor Rb

    m3 = aes128_enc_int(m1);
    _mm_storeu_si128(reinterpret_cast<__m128i *>(res), m3);
}

#endif  // SRC_CPP_AES_HPP_
