import React, { useMemo } from 'react';
import { Trans } from '@lingui/macro';
import type { Wallet } from '@chia/api';
import { DropdownActions } from '@chia/core';
import {
  AutoAwesome as AutoAwesomeIcon,
  PermIdentity as PermIdentityIcon,
} from '@mui/icons-material';
import { ListItemIcon, MenuItem } from '@mui/material';
import {
  useGetDIDsQuery,
  useGetNFTWallets,
  useGetNFTWalletsWithDIDsQuery,
} from '@chia/api-react';
import { NFTsSmall as NFTsSmallIcon } from '@chia/icons';
import { orderBy } from 'lodash';

type Profile = Wallet & {
  nftWalletId: number;
};

function useProfiles() {
  // const { data: wallets, isLoading, error } = useGetWalletsQuery();
  const { data: dids, isLoading, error } = useGetDIDsQuery();
  const { data: nftWallets, isLoading: loadingNFTWallets } =
    useGetNFTWalletsWithDIDsQuery();

  const profiles: Profile[] = useMemo(() => {
    if (!dids || !nftWallets) {
      return [];
    }
    const profiles = nftWallets.map((nftWallet: Wallet) => {
      return {
        ...dids.find(
          (didWallet: Wallet) => didWallet.id === nftWallet.didWalletId,
        ),
        nftWalletId: nftWallet.walletId,
      };
    });

    return orderBy(profiles, ['name'], ['asc']);
  }, [dids, nftWallets]);

  return {
    isLoading: isLoading || loadingNFTWallets,
    data: profiles,
    error,
  };
}

export type NFTGallerySidebarProps = {
  walletId?: number;
  onChange: (walletId?: number) => void;
};

export default function NFTProfileDropdown(props: NFTGallerySidebarProps) {
  const { onChange, walletId } = props;
  const { isLoading: isLoadingProfiles, data: profiles } = useProfiles();
  const { wallets: nftWallets, isLoading: isLoadingNFTWallets } =
    useGetNFTWallets();

  const inbox: Wallet | undefined = useMemo(() => {
    if (isLoadingProfiles || isLoadingNFTWallets) {
      return undefined;
    }

    const nftWalletIds = nftWallets.map((nftWallet: Wallet) => nftWallet.id);
    const profileWalletIds = new Set(
      profiles.map((profile) => profile.nftWalletId),
    );
    const inboxWalletId = nftWalletIds.find(
      (nftWalletId: number) => !profileWalletIds.has(nftWalletId),
    );
    return nftWallets.find((wallet: Wallet) => wallet.id === inboxWalletId);
  }, [profiles, nftWallets, isLoadingProfiles, isLoadingNFTWallets]);

  const remainingNFTWallets = useMemo(() => {
    if (isLoadingProfiles || isLoadingNFTWallets) {
      return undefined;
    }

    const nftWalletsWithoutDIDs = nftWallets.filter((nftWallet: Wallet) => {
      return (
        nftWallet.id !== inbox.id &&
        profiles.find(
          (profile: Profile) => profile.nftWalletId === nftWallet.id,
        ) === undefined
      );
    });

    return nftWalletsWithoutDIDs;
  }, [profiles, nftWallets, inbox, isLoadingProfiles, isLoadingNFTWallets]);

  const label = useMemo(() => {
    if (isLoadingProfiles || isLoadingNFTWallets) {
      return 'Loading...';
    }

    if (inbox && inbox.id === walletId) {
      return <Trans>Unassigned NFTs</Trans>;
    }

    const profile = profiles?.find(
      (item: Profile) => item.nftWalletId === walletId,
    );

    if (profile) {
      return profile.name;
    }

    const nftWallet = remainingNFTWallets?.find(
      (wallet: Wallet) => wallet.id === walletId,
    );

    if (nftWallet) {
      return `${nftWallet.name} ${nftWallet.id}`;
    }

    return <Trans>All NFTs</Trans>;
  }, [
    profiles,
    remainingNFTWallets,
    isLoadingProfiles,
    isLoadingNFTWallets,
    walletId,
    inbox,
  ]);

  function handleWalletChange(newWalletId?: number) {
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
            selected={walletId === undefined}
          >
            <ListItemIcon>
              <AutoAwesomeIcon />
            </ListItemIcon>
            <Trans>All NFTs</Trans>
          </MenuItem>
          {inbox && (
            <MenuItem
              key="inbox"
              onClick={() => {
                onClose();
                handleWalletChange(inbox.id);
              }}
              selected={walletId === inbox.id}
            >
              <ListItemIcon>
                <NFTsSmallIcon />
              </ListItemIcon>
              <Trans>Unassigned NFTs</Trans>
            </MenuItem>
          )}
          {(remainingNFTWallets ?? []).map((wallet: Wallet) => {
            return (
              <MenuItem
                key={wallet.id}
                onClick={() => {
                  onClose();
                  handleWalletChange(wallet.id);
                }}
                selected={walletId === wallet.id}
              >
                <ListItemIcon>
                  <NFTsSmallIcon />
                </ListItemIcon>
                {wallet.name} {wallet.id}
              </MenuItem>
            );
          })}
          {(profiles ?? []).map((profile: Profile) => (
            <MenuItem
              key={profile.nftWalletId}
              onClick={() => {
                onClose();
                handleWalletChange(profile.nftWalletId);
              }}
              selected={profile.nftWalletId === walletId}
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
