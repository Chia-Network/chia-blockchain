import type WalletType from '../constants/WalletType';
import type Wallet from '../types/Wallet';

// export const initial_wallet = createWallet(0, "Chia Wallet", "STANDARD_WALLET", "");

export default function createWallet(
  id: number,
  name: string,
  type: WalletType,
  data: Object,
): Wallet {
  return {
    id,
    name,
    type,
    data,
    balance_total: 0,
    balance_pending: 0,
    balance_spendable: 0,
    balance_frozen: 0,
    balance_change: 0,
    transactions: [],
    address: '',
    colour: '',
    mydid: '',
    didcoin: '',
    backup_dids: [],
    dids_num_req: 0,
    did_attest: '',
    sending_transaction: false,
    send_transaction_result: '',
  };
}
