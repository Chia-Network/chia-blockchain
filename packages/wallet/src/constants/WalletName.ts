import { defineMessage } from '@lingui/macro';
import WalletType from './WalletType';

const WalletName = {
  [WalletType.STANDARD_WALLET]: defineMessage({
    message: 'Standard Wallet',
  }),
  [WalletType.RATE_LIMITED]: defineMessage({
    message: 'RL Wallet',
  }),
  [WalletType.ATOMIC_SWAP]: defineMessage({
    message: 'Atomic Swap Wallet',
  }),
  [WalletType.AUTHORIZED_PAYEE]: defineMessage({
    message: 'Authorized Payee Wallet',
  }),
  [WalletType.MULTI_SIG]: defineMessage({
    message: 'Multi Sig Wallet',
  }),
  [WalletType.CUSTODY]: defineMessage({
    message: 'Custody Wallet',
  }),
  [WalletType.CAT]: defineMessage({
    message: 'CAT Wallet',
  }),
  [WalletType.RECOVERABLE]: defineMessage({
    message: 'Recoverable Wallet',
  }),
  [WalletType.DISTRIBUTED_ID]: defineMessage({
    message: 'DID Wallet',
  }),
  [WalletType.POOLING_WALLET]: defineMessage({
    message: 'Pooling Wallet',
  }),
}

export default WalletName;
