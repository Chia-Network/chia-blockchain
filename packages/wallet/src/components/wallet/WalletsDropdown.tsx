import React, { useMemo } from 'react';
import { ListItemIcon, ListItemText, Typography } from '@material-ui/core';
import { useSelector } from 'react-redux';
import { Dropdown, Flex } from '@chia/core';
import { useHistory } from 'react-router';
import type { RootState } from '../../modules/rootReducer';
import WalletName from '../../constants/WalletName';
import useTrans from '../../hooks/useTrans';
import WalletIcon from './WalletIcon';
import WalletBadge from './WalletBadge';

type Props = {
  walletId: number;
};

export default function WalletsDropdown(props: Props) {
  const { walletId } = props;
  const history = useHistory();
  const trans = useTrans();
  const wallets = useSelector((state: RootState) => state.wallet_state.wallets);

  const options = useMemo(() => {
    if (!wallets) {
      return [];
    }

    return wallets.map((wallet) => {
      const primaryTitle = wallet.name;
      const secondaryTitle = trans(WalletName[wallet.type]);

      const hasSameTitle = primaryTitle.toLowerCase() === secondaryTitle.toLowerCase();
      return {
        wallet,
        value: wallet.id,
        label: (
          <>
            <ListItemIcon>
              <WalletIcon wallet={wallet} />
            </ListItemIcon>
            <ListItemText
              primary={(
                <Flex gap={1} alignItems="center">
                  <Typography>{primaryTitle}</Typography>
                  <WalletBadge wallet={wallet} fontSize="small" tooltip />
                </Flex>
              )}
              secondary={!hasSameTitle ? secondaryTitle: undefined}
              secondaryTypographyProps={{
                variant: 'caption',
              }}
            />
            
          </>
        ),
      };
    });
  }, [wallets, walletId]);

  function handleSelectWallet(walletId: number) {
    history.push(`/dashboard/wallets/${walletId}`);
  }

  if (!wallets) {
    return (
      <Loading />
    );
  }

  return (
    <Dropdown 
      options={options}
      selected={walletId}
      onSelect={handleSelectWallet}
      anchorOrigin={{
        vertical: 'bottom',
        // horizontal: 'center',
      }}
      transformOrigin={{
        vertical: 'top',
        // horizontal: 'center',
      }}
    >
      {(option) => !!option?.wallet && (
        <Flex gap={1} alignItems="center">
          <Typography>{option.wallet.name}</Typography>
          <WalletBadge wallet={option.wallet} fontSize="small" />
        </Flex>
      )}
    </Dropdown>
  );
}
