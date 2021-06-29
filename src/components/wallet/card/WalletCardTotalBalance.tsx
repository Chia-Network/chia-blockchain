import React from 'react';
import { Trans } from '@lingui/macro';
import styled from 'styled-components';
import WalletGraph from '../WalletGraph';
import FarmCard from '../../farm/card/FarmCard';
import useWallet from '../../../hooks/useWallet';
import useCurrencyCode from '../../../hooks/useCurrencyCode';
import { mojo_to_chia_string } from '../../../util/chia';

const StyledGraphContainer = styled.div`
  margin-left: -1rem;
  margin-right: -1rem;
  margin-top: 1rem;
  margin-bottom: -1rem;
`;

type Props = {
  wallet_id: number;
};

export default function WalletCardTotalBalance(props: Props) {
  const { wallet_id } = props;

  const { wallet, loading } = useWallet(wallet_id);
  const currencyCode = useCurrencyCode();

  const value = wallet?.wallet_balance?.confirmed_wallet_balance;

  return (
    <FarmCard
      loading={loading}
      title={<Trans>Total Balance</Trans>}
      tooltip={
        <Trans>
          This is the total amount of chia in the blockchain at the current peak
          sub block that is controlled by your private keys. It includes frozen
          farming rewards, but not pending incoming and outgoing transactions.
        </Trans>
      }
      value={
        <>
          {mojo_to_chia_string(value)} {currencyCode}
        </>
      }
      description={
        <StyledGraphContainer>
          <WalletGraph walletId={wallet_id} height={120} />
        </StyledGraphContainer>
      }
    />
  );
}
