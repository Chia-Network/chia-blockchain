import React, { ReactElement } from 'react';
import { Grid } from '@material-ui/core';
import WalletCardTotalBalance from './card/WalletCardTotalBalance';
import WalletCardSpendableBalance from './card/WalletCardSpendableBalance';
import WalletCardPendingTotalBalance from './card/WalletCardPendingTotalBalance';
import WalletCardPendingBalance from './card/WalletCardPendingBalance';
import WalletCardPendingChange from './card/WalletCardPendingChange';

type Props = {
  walletId: number;
  totalBalanceTooltip?: ReactElement<any>;
  spendableBalanceTooltip?: ReactElement<any>;
  pendingTotalBalanceTooltip?: ReactElement<any>;
  pendingBalanceTooltip?: ReactElement<any>;
  pendingChangeTooltip?: ReactElement<any>;
};

export default function WalletCards(props: Props) {
  const {
    walletId,
    totalBalanceTooltip,
    spendableBalanceTooltip,
    pendingTotalBalanceTooltip,
    pendingBalanceTooltip,
    pendingChangeTooltip,
  } = props;

  return (
    <div>
      <Grid spacing={3} alignItems="stretch" container>
        <Grid xs={12} md={4} item>
          <WalletCardTotalBalance 
            walletId={walletId}
            tooltip={totalBalanceTooltip}
          />
        </Grid>
        <Grid xs={12} md={8} item>
          <Grid spacing={3} alignItems="stretch" container>
            <Grid xs={12} sm={6} item>
              <WalletCardSpendableBalance 
                walletId={walletId}
                tooltip={spendableBalanceTooltip}
              />
            </Grid>
            <Grid xs={12} sm={6} item>
              <WalletCardPendingTotalBalance 
                walletId={walletId}
                tooltip={pendingTotalBalanceTooltip}
              />
            </Grid>
            <Grid xs={12} sm={6} item>
              <WalletCardPendingBalance
                walletId={walletId}
                tooltip={pendingBalanceTooltip}
              />
            </Grid>
            <Grid xs={12} sm={6} item>
              <WalletCardPendingChange 
                walletId={walletId}
                tooltip={pendingChangeTooltip}
              />
            </Grid>
          </Grid>
        </Grid>
      </Grid>
    </div>
  );
}

WalletCards.defaultProps = {
  totalBalanceTooltip: undefined,
  spendableBalanceTooltip: undefined,
  pendingTotalBalanceTooltip: undefined,
  pendingBalanceTooltip: undefined,
  pendingChangeTooltip: undefined,
};
