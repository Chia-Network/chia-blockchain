import React from 'react';
import { Trans } from '@lingui/macro';
import { Grid } from '@material-ui/core';
import WalletCardTotalBalance from '../card/WalletCardTotalBalance';
import WalletCardSpendableBalance from '../card/WalletCardSpendableBalance';
import WalletCardPendingTotalBalance from '../card/WalletCardPendingTotalBalance';
import WalletCardPendingBalance from '../card/WalletCardPendingBalance';
import WalletCardPendingChange from '../card/WalletCardPendingChange';

type Props = {
  wallet_id: number;
};

export default function WalletCards(props: Props) {
  const { wallet_id } = props;

  return (
    <div>
      <Grid spacing={3} alignItems="stretch" container>
        <Grid xs={12} md={4} item>
          <WalletCardTotalBalance 
            wallet_id={wallet_id}
            tooltip={
              <Trans>
                This is the total amount of chia in the blockchain at the current peak
                sub block that is controlled by your private keys. It includes frozen
                farming rewards, but not pending incoming and outgoing transactions.
              </Trans>
            }
          />
        </Grid>
        <Grid xs={12} md={8} item>
          <Grid spacing={3} alignItems="stretch" container>
            <Grid xs={12} sm={6} item>
              <WalletCardSpendableBalance wallet_id={wallet_id} />
            </Grid>
            <Grid xs={12} sm={6} item>
              <WalletCardPendingTotalBalance wallet_id={wallet_id} />
            </Grid>
            <Grid xs={12} sm={6} item>
              <WalletCardPendingBalance wallet_id={wallet_id} />
            </Grid>
            <Grid xs={12} sm={6} item>
              <WalletCardPendingChange wallet_id={wallet_id} />
            </Grid>
          </Grid>
        </Grid>
      </Grid>
    </div>
  );
}
