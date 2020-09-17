import WalletType from "./WalletType";

interface Wallet {
  id: number,
  name: string,
  type: WalletType,
  data: Object,
  balance_total: number,
  balance_pending: number,
  balance_spendable: number,
  balance_frozen: number,
  balance_change: number,
  transactions: [],
  puzzle_hash: string,
  colour: string,
  send_transaction_result: string,
};

export default Wallet;
