import React, { useMemo } from 'react';
import { ListItemIcon, ListItemText, Typography } from '@material-ui/core';
import { Dropdown, Flex, Loading } from '@chia/core';
import { useGetWalletsQuery } from '@chia/api-react';
import { useHistory } from 'react-router';
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
  const { data: wallets, isLoading } = useGetWalletsQuery();

  const options = useMemo(() => {
    if (isLoading) {
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
  }, [wallets, walletId, isLoading]);

  function handleSelectWallet(walletId: number) {
    history.push(`/dashboard/wallets/${walletId}`);
  }

  if (isLoading) {
    return (
      <Loading size="small" />
    );
  }

  return (
    <Dropdown 
      options={options}
      selected={walletId}
      onSelect={handleSelectWallet}
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
