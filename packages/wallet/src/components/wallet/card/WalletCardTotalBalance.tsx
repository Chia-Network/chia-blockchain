import React from 'react';
import { Trans } from '@lingui/macro';
import styled from 'styled-components';
import WalletGraph from '../WalletGraph';
import FarmCard from '../../farm/card/FarmCard';
import useWallet from '../../../hooks/useWallet';
import useCurrencyCode from '../../../hooks/useCurrencyCode';
import { mojo_to_chia_string, mojo_to_colouredcoin_string } from '../../../util/chia';
import getCatUnit from '../../../util/getCatUnit';
import WalletType from '../../../constants/WalletType';

const StyledGraphContainer = styled.div`
  margin-left: -1rem;
  margin-right: -1rem;
  margin-top: 1rem;
  margin-bottom: -1rem;
`;

type Props = {
  wallet_id: number;
  tooltip?: ReactNode;
};

export default function WalletCardTotalBalance(props: Props) {
  const { wallet_id, tooltip } = props;

  const { wallet, loading } = useWallet(wallet_id);
  const currencyCode = useCurrencyCode();

  const value = wallet?.wallet_balance?.confirmed_wallet_balance;
  const formatedValue = wallet?.type === WalletType.CAT
    ? mojo_to_colouredcoin_string(value)
    : mojo_to_chia_string(value);

  const formatedCurrencyCode = wallet?.type === WalletType.CAT
    ? getCatUnit(wallet?.name)
    : currencyCode;

  return (
    <FarmCard
      loading={loading}
      title={<Trans>Total Balance</Trans>}
      tooltip={tooltip}
      value={
        <>
          {formatedValue} {formatedCurrencyCode}
        </>
      }
      description={
        <StyledGraphContainer>
          <WalletGraph walletId={wallet_id} height={114} />
        </StyledGraphContainer>
      }
    />
  );
}
