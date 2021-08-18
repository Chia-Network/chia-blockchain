import time
import json
import unittest
from secrets import token_bytes
from chives.util.ints import uint32

from blspy import AugSchemeMPL, G1Element, G2Element
from hashlib import sha256

from chives.consensus.coinbase import create_puzzlehash_for_pk
from chives.util.bech32m import decode_puzzle_hash, encode_puzzle_hash
from chives.util.config import load_config
from chives.util.default_root import DEFAULT_ROOT_PATH
from chives.util.ints import uint32
from chives.util.keychain import Keychain, bytes_from_mnemonic, bytes_to_mnemonic, generate_mnemonic, mnemonic_to_seed
from chives.wallet.derive_keys import master_sk_to_farmer_sk, master_sk_to_pool_sk, master_sk_to_wallet_sk

import redis
r = redis.Redis(host='localhost', port=6379, decode_responses=True)

class TesKeychain(unittest.TestCase):
    def test_basic_add_delete(self):
        
        mnemonic = generate_mnemonic()
        mnemonic = "hen battle gauge crouch dose weasel blind noble ugly pull cruel mutual slight tragic bean rule once garage valley ritual still couple charge rich"
        entropy = bytes_from_mnemonic(mnemonic)
        seed = mnemonic_to_seed(mnemonic, "")
        seed_key = AugSchemeMPL.key_gen(seed)
        masterPublicKey = seed_key.get_g1()
        fingerprint = masterPublicKey.get_fingerprint()
        
        #print(mnemonic);
        #print(entropy)
        #print(seed)
        #print(seed_key)
        print(masterPublicKey)
        #print(fingerprint)
        
        RS = {}
        RS['mnemonic'] = mnemonic
        #RS['seed'] = seed
        #RS['masterPrivateKey'] = seed_key
        #RS['masterPublicKey'] = masterPublicKey
        RS['fingerprint'] = fingerprint
        
        print("##################################################################")
        
        PairKeysDict = {}
        puzzlehashs = []
        private_keys = []
        public_keys = []
        addresses = []
        
        root_path = DEFAULT_ROOT_PATH
        config = load_config(root_path, "config.yaml")
        selected = config["selected_network"]
        prefix = config["network_overrides"]["config"][selected]["address_prefix"]
        
        
        for i in range(0, 50):
            private_key: PrivateKey = master_sk_to_wallet_sk(seed_key, uint32(i))
            public_key = private_key.get_g1()
            puzzlehash = create_puzzlehash_for_pk(public_key)
            address = encode_puzzle_hash(puzzlehash, prefix)
            #PairKeys = {}
            #PairKeys['index'] = i
            #PairKeys['private_key'] = private_key
            #PairKeys['public_key'] = public_key
            #PairKeys['puzzlehash'] = puzzlehash
            #PairKeys['address'] = address
            PairKeysDict[i] = address
            #print(f"i: {i}")
            #print(f"private_key: {private_key}")
            #print(f"public_key: {public_key}")
            #print(f"puzzlehash: {puzzlehash}")
            #print(f"address: {address}")
            
        RS['PairKeysDict'] = PairKeysDict
        
        
        y = json.dumps(RS)
        hashkey = sha256(mnemonic.encode('utf-8')).hexdigest()
        r.hset("CHIVES_KEYS_LIST",hashkey,y)
        print(y)
        #print(private_keys)
        #print(public_keys)
        #print(puzzlehashs)
        #print(addresses)
        #print("##################################################################")
        
        #kc: Keychain = Keychain(testing=True)
        #kc.delete_all_keys()
        #kc.add_private_key(mnemonic, "")
        #print(kc.get_all_private_keys())
        #print(kc.get_all_public_keys())

if __name__ == "__main__":
    unittest.main()
