import React, { useMemo, useState } from 'react';
import { Trans } from '@lingui/macro';
import type { Wallet } from '@chia/api';
import { DropdownActions } from '@chia/core';
import {
  AutoAwesome as AutoAwesomeIcon,
  PermIdentity as PermIdentityIcon,
} from '@mui/icons-material';
import { Box, ListItemIcon, MenuItem, Typography } from '@mui/material';
import { WalletType } from '@chia/api';
import {
  useGetWalletsQuery,
  useGetNFTWallets,
  useGetNFTWalletsWithDIDsQuery,
} from '@chia/api-react';
import { NFTsSmall as NFTsSmallIcon } from '@chia/icons';
import { orderBy } from 'lodash';

type Profile = Wallet & {
  nftWalletId: number;
};

function useProfiles() {
  const { data: wallets, isLoading, error } = useGetWalletsQuery();
  const { data: nftWallets, isLoading: loadingNFTWallets } =
    useGetNFTWalletsWithDIDsQuery();

  const profiles: Profile[] = useMemo(() => {
    if (!wallets || !nftWallets) {
      return [];
    }
    const didWallets = wallets.filter(
      (wallet) => wallet.type === WalletType.DISTRIBUTED_ID,
    );

    const profiles = nftWallets.map((nftWallet) => {
      return {
        ...didWallets.find(
          (didWallet) => didWallet.id === nftWallet.didWalletId,
        ),
        nftWalletId: nftWallet.walletId,
      };
    });

    return orderBy(profiles, ['name'], ['asc']);
  }, [wallets, nftWallets]);

  return {
    isLoading,
    data: profiles,
    error,
  };
}

export type NFTGallerySidebarProps = {
  onChange: (walletId?: number) => void;
};

export default function NFTProfileDropdown(props: NFTGallerySidebarProps) {
  const { onChange } = props;
  const { isLoading: isLoadingProfiles, data: profiles } = useProfiles();
  const { wallets: nftWallets, isLoadingNFTWallets } = useGetNFTWallets();
  const [selectedWalletId, setSelectedWalletId] = useState<
    number | undefined
  >();

  const inbox: Wallet | undefined = useMemo(() => {
    if (isLoadingProfiles || isLoadingNFTWallets) {
      return undefined;
    }

    const nftWalletIds = nftWallets.map((nftWallet) => nftWallet.walletId);
    const profileWalletIds = new Set(
      profiles.map((profile) => profile.nftWalletId),
    );
    const inboxWalletId = nftWalletIds.find(
      (walletId) => !profileWalletIds.has(walletId),
    );
    return nftWallets.find((wallet) => wallet.walletId === inboxWalletId);
  }, [profiles, nftWallets, isLoadingProfiles, isLoadingNFTWallets]);

  const label = useMemo(() => {
    if (isLoadingProfiles || isLoadingNFTWallets) {
      return 'Loading...';
    }

    if (inbox && selectedWalletId === inbox) {
      return <Trans>NFT Inbox</Trans>;
    }

    const profile = profiles?.find(
      (item: Profile) => item.nftWalletId === selectedWalletId,
    );
    return profile?.name || <Trans>All Profiles</Trans>;
  }, [
    profiles,
    nftWallets,
    isLoadingProfiles,
    isLoadingNFTWallets,
    selectedWalletId,
  ]);

  function handleWalletChange(newWalletId?: number) {
    setSelectedWalletId(newWalletId);
    onChange?.(newWalletId);
  }

  return (
    <DropdownActions
      onSelect={handleWalletChange}
      label={label}
      variant="text"
      color="secondary"
      size="large"
    >
      {({ onClose }) => (
        <>
          <MenuItem
            key="all"
            onClick={() => {
              onClose();
              handleWalletChange();
            }}
            selected={selectedWalletId === undefined}
          >
            <ListItemIcon>
              <AutoAwesomeIcon />
            </ListItemIcon>
            <Trans>All</Trans>
          </MenuItem>
          {inbox && (
            <MenuItem
              key="inbox"
              onClick={() => {
                onClose();
                handleWalletChange(inbox.id);
              }}
              selected={selectedWalletId === inbox.id}
            >
              <ListItemIcon>
                <NFTsSmallIcon />
              </ListItemIcon>
              <Trans>NFTs</Trans>
            </MenuItem>
          )}
          {(profiles ?? []).map((profile: Profile) => (
            <MenuItem
              key={profile.nftWalletId}
              onClick={() => {
                onClose();
                handleWalletChange(profile.nftWalletId);
              }}
              selected={profile.nftWalletId === selectedWalletId}
            >
              <ListItemIcon>
                <PermIdentityIcon />
              </ListItemIcon>
              {profile.name}
            </MenuItem>
          ))}
        </>
      )}
    </DropdownActions>
  );
}
