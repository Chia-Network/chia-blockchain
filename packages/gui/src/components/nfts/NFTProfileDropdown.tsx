import React, { useMemo, useState } from 'react';
import { Trans } from '@lingui/macro';
import { DropdownActions } from '@chia/core';
import { Box, MenuItem, Typography } from '@mui/material';
import { WalletType } from '@chia/api';
import { orderBy } from 'lodash';
import { useGetWalletsQuery } from '@chia/api-react';

function useProfiles() {
  const { data: wallets, isLoading, error } = useGetWalletsQuery();

  const didWallets = useMemo(() => {
    if (!wallets) {
      return [];
    }
    const didWallets = wallets.filter((wallet) => wallet.type === WalletType.DISTRIBUTED_ID);
    return orderBy(didWallets, ['name'], ['asc']);
  }, [wallets]);

  return {
    isLoading,
    data: didWallets,
    error,
  };
}

export type NFTGallerySidebarProps = {
  onChange: (walletId?: number) => void;
};

export default function NFTProfileDropdown(props: NFTGallerySidebarProps) {
  const { onChange } = props;
  const { isLoading, data } = useProfiles();
  const [selectedWalletId, setSelectedWalletId] = useState<number | undefined>();

  const label = useMemo(() => {
    if (isLoading) {
      return 'Loading...';
    }

    const wallet = data?.find(item => item.id === selectedWalletId);
    return wallet?.name || <Trans>All Profiles</Trans>;
  }, [data, isLoading, selectedWalletId]);

  function handleWalletChange(newWalletId?: number) {
    setSelectedWalletId(newWalletId);
    onChange?.(newWalletId);
  }

  return (
    <DropdownActions onSelect={handleWalletChange} label={label} variant="text" color="secondary" size="large" >
      {({ onClose }) => (
        <>
          {data.map((wallet) => (
            <MenuItem
              key={wallet.id}
              onClick={() => { onClose(); handleWalletChange(wallet.id); }}
              selected={wallet.id === selectedWalletId}
            >
              {wallet.name}
            </MenuItem>
          ))}
          <MenuItem key="all" onClick={() => { onClose(); handleWalletChange(); }} selected={selectedWalletId === undefined}>
            <Trans>All</Trans>
          </MenuItem>
        </>
      )}
    </DropdownActions>
  );
}
