from src.cmds.tx import create_unsigned_tx_from_json

class TestTxCreate:
    def test_create_unsigned_tx_from_json(self):
        with open("tests/tx/utx-in.json") as f:
            json_tx = f.read()
        create_unsigned_tx_from_json(json_tx)
