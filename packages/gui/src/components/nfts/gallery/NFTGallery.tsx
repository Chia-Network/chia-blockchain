import React, { useState, useMemo } from 'react';
import { Flex, LayoutDashboardSub, Loading, /*useTrans,*/ usePersistState } from '@chia/core';
// import { defineMessage } from '@lingui/macro';
import { WalletReceiveAddressField } from '@chia/wallets';
import type { NFTInfo, Wallet } from '@chia/api';
import { useGetNFTWallets } from '@chia/api-react';
import { Box, Grid } from '@mui/material';
// import NFTGallerySidebar from './NFTGallerySidebar';
import NFTCardLazy from '../NFTCardLazy';
// import Search from './NFTGallerySearch';
import { NFTContextualActionTypes } from '../NFTContextualActions';
import type NFTSelection from '../../../types/NFTSelection';
import useFetchNFTs from '../../../hooks/useFetchNFTs';
import NFTProfileDropdown from '../NFTProfileDropdown';
import NFTGalleryHero from './NFTGalleryHero';

function searchableNFTContent(nft: NFTInfo) {
  const items = [nft.$nftId, nft.dataUris?.join(' ') ?? '', nft.launcherId];

  return items.join(' ').toLowerCase();
}

export default function NFTGallery() {
  const { wallets: nftWallets, isLoading: isLoadingWallets } =
    useGetNFTWallets();
  const { nfts, isLoading: isLoadingNFTs } = useFetchNFTs(
    nftWallets.map((wallet: Wallet) => wallet.id),
  );
  const isLoading = isLoadingWallets || isLoadingNFTs;
  const [search/*, setSearch*/] = useState<string>('');

  const [walletId, setWalletId] = usePersistState<
    number | undefined
  >(undefined, 'nft-profile-dropdown');

  // const t = useTrans();
  const [selection, setSelection] = useState<NFTSelection>({
    items: [],
  });

  const filteredData = useMemo(() => {
    if (!nfts) {
      return nfts;
    }

    return nfts.filter((nft) => {
      if (walletId !== undefined && nft.walletId !== walletId) {
        return false;
      }

      const content = searchableNFTContent(nft);
      if (search) {
        return content.includes(search.toLowerCase());
      }

      return true;
    });
  }, [search, walletId, nfts]);

  function handleSelect(nft: NFTInfo, selected: boolean) {
    setSelection((currentSelection) => {
      const { items } = currentSelection;

      return {
        items: selected
          ? [...items, nft]
          : items.filter((item) => item.$nftId !== nft.$nftId),
      };
    });
  }

  if (isLoading) {
    return <Loading center />;
  }

  return (
    <LayoutDashboardSub
      // sidebar={<NFTGallerySidebar onWalletChange={setWalletId} />}
      header={
        <Flex gap={2} alignItems="center" flexWrap="wrap" justifyContent="space-between">
          <NFTProfileDropdown onChange={setWalletId} walletId={walletId} />
          <Flex
            justifyContent="flex-end"
            alignItems="center"
          >
            {/*
            <Search
              onChange={setSearch}
              value={search}
              placeholder={t(defineMessage({ message: `Search...` }))}
            />
            */}
            {/*
            <NFTContextualActions selection={selection} />
            */}
            <Box width={{ xs: 300, sm: 330, md: 550, lg: 630 }}>
              <WalletReceiveAddressField variant="outlined" size="small" fullWidth />
            </Box>
          </Flex>
        </Flex>
      }
    >
      {!filteredData?.length ? (
        <NFTGalleryHero />
      ) : (
        <Grid spacing={2} alignItems="stretch" container>
          {filteredData?.map((nft: NFTInfo) => (
            <Grid xs={12} sm={6} md={4} lg={4} xl={3} key={nft.$nftId} item>
              <NFTCardLazy
                nft={nft}
                onSelect={(selected) => handleSelect(nft, selected)}
                selected={selection.items.some(
                  (item) => item.$nftId === nft.$nftId,
                )}
                canExpandDetails={true}
                availableActions={NFTContextualActionTypes.All}
              />
            </Grid>
          ))}
        </Grid>
      )}

    </LayoutDashboardSub>
  );
}
