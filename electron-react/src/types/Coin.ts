import type WalletType from './WalletType';

type Coin = {
  confirmed_block_index: number,
  spent_block_index: number,
  spent: boolean,
  coinbase: boolean,
  wallet_type: WalletType,
  wallet_id: number,
};

export default Coin;
