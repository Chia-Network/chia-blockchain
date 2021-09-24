import type WalletType from '../constants/WalletType';
import type Wallet from '../types/Wallet';

// deprecated
export default function createWallet(
  id: number,
  name: string,
  type: WalletType,
  data: Object,
  details?: Object,
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
    did_rec_puzhash: '',
    did_rec_pubkey: '',
    sending_transaction: false,
    send_transaction_result: '',
    ...details,
  };
}
