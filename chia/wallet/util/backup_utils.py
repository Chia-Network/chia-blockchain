import base64
import json
from typing import Any

import aiohttp
from blspy import AugSchemeMPL, PrivateKey, PublicKeyMPL, SignatureMPL
from cryptography.fernet import Fernet

from chia.server.server import ssl_context_for_root
from chia.ssl.create_ssl import get_mozilla_ca_crt
from chia.util.byte_types import hexstr_to_bytes
from chia.util.hash import std_hash
from chia.wallet.derive_keys import master_sk_to_backup_sk
from chia.wallet.util.wallet_types import WalletType


def open_backup_file(file_path, private_key):
    backup_file_text = file_path.read_text()
    backup_file_json = json.loads(backup_file_text)
    meta_data = backup_file_json["meta_data"]
    meta_data_bytes = json.dumps(meta_data).encode()
    sig = backup_file_json["signature"]

    backup_pk = master_sk_to_backup_sk(private_key)
    my_pubkey = backup_pk.get_g1()
    key_base_64 = base64.b64encode(bytes(backup_pk))
    f = Fernet(key_base_64)

    encrypted_data = backup_file_json["data"].encode()
    msg = std_hash(encrypted_data) + std_hash(meta_data_bytes)

    signature = SignatureMPL.from_bytes(hexstr_to_bytes(sig))
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


async def post(session: aiohttp.ClientSession, url: str, data: Any):
    mozilla_root = get_mozilla_ca_crt()
    ssl_context = ssl_context_for_root(mozilla_root)
    response = await session.post(url, json=data, ssl=ssl_context)
    return await response.json()


async def get(session: aiohttp.ClientSession, url: str):
    response = await session.get(url)
    return await response.text()


async def upload_backup(host: str, backup_text: str):
    request = {"backup": backup_text}
    session = aiohttp.ClientSession()
    nonce_url = f"{host}/upload_backup"
    upload_response = await post(session, nonce_url, request)
    await session.close()
    return upload_response


async def download_backup(host: str, private_key: PrivateKey):
    session = aiohttp.ClientSession()
    try:
        backup_privkey = master_sk_to_backup_sk(private_key)
        backup_pubkey = bytes(backup_privkey.get_g1()).hex()
        # Get nonce
        nonce_request = {"pubkey": backup_pubkey}
        nonce_url = f"{host}/get_download_nonce"
        nonce_response = await post(session, nonce_url, nonce_request)
        nonce = nonce_response["nonce"]

        # Sign nonce
        signature = bytes(AugSchemeMPL.sign(backup_privkey, std_hash(hexstr_to_bytes(nonce)))).hex()
        # Request backup url
        get_backup_url = f"{host}/download_backup"
        backup_request = {"pubkey": backup_pubkey, "signature": signature}
        backup_response = await post(session, get_backup_url, backup_request)

        if backup_response["success"] is False:
            raise ValueError("No backup on backup service")

        # Download from s3
        backup_url = backup_response["url"]
        backup_text = await get(session, backup_url)
        await session.close()
        return backup_text
    except Exception as e:
        await session.close()
        # Pass exception
        raise e
