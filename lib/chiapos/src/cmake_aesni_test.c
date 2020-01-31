#include <aesni.h>

int main() {
    uint8_t enc_key[32];
    uint8_t in[16];
    uint8_t out[16];

    memset(enc_key,0x00,sizeof(enc_key));
    memset(in,0x00,sizeof(in));

    ni_aes_load_key(enc_key, sizeof(enc_key));
    ni_aes256_enc(in, out);

    return 0;
}

