import base64
import json

from blspy import PublicKeyMPL, SignatureMPL, AugSchemeMPL
from cryptography.fernet import Fernet

from src.util.byte_types import hexstr_to_bytes
from src.util.hash import std_hash
from src.wallet.derive_keys import master_sk_to_backup_sk
from src.wallet.util.wallet_types import WalletType


def open_backup_file(file_path, private_key):
    backup_file_text = file_path.read_text()
    backup_file_json = json.loads(backup_file_text)
    meta_data = backup_file_json["meta_data"]

    backup_pk = master_sk_to_backup_sk(private_key)
    my_pubkey = backup_pk.get_g1()
    key_base_64 = base64.b64encode(bytes(backup_pk))
    f = Fernet(key_base_64)

    encrypted_data = backup_file_json["data"].encode()
    msg = std_hash(encrypted_data)

    signature = SignatureMPL.from_bytes(hexstr_to_bytes(meta_data["signature"]))
    pubkey = PublicKeyMPL.from_bytes(hexstr_to_bytes(meta_data["pubkey"]))

    sig_match_my = AugSchemeMPL.verify(my_pubkey, msg, signature)
    sig_match_backup = AugSchemeMPL.verify(pubkey, msg, signature)

    assert sig_match_my is True
    assert sig_match_backup is True

    data_bytes = f.decrypt(encrypted_data)
    data_text = data_bytes.decode()
    data_json = json.loads(data_text)
    unencrypted = {}
    unencrypted["data"] = data_json
    unencrypted["meta_data"] = meta_data
    return unencrypted


def get_backup_info(file_path, private_key):
    json_dict = open_backup_file(file_path, private_key)
    data = json_dict["data"]
    wallet_list_json = data["wallet_list"]

    info_dict = {}
    wallets = []
    for wallet_info in wallet_list_json:
        wallet = {}
        wallet["name"] = wallet_info["name"]
        wallet["type"] = wallet_info["type"]
        wallet["type_name"] = WalletType(wallet_info["type"]).name
        wallet["id"] = wallet_info["id"]
        wallet["data"] = wallet_info["data"]
        wallets.append(wallet)

    info_dict["version"] = data["version"]
    info_dict["fingerprint"] = data["fingerprint"]
    info_dict["timestamp"] = data["timestamp"]
    info_dict["wallets"] = wallets

    return info_dict
