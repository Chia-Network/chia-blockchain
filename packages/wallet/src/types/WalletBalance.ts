type WalletBalance = {
  wallet_id: number;
  confirmed_wallet_balance: number;
  max_send_amount: number;
  pending_change: number;
  pending_coin_removal_count: number;
  spendable_balance: number;
  unconfirmed_wallet_balance: number;
  unspent_coin_count: number;
  balance_pending: number;
};

export default WalletBalance;
