import React, { useState, useMemo } from 'react';
import { Flex, LayoutDashboardSub, Loading, useTrans } from '@chia/core';
import { defineMessage } from '@lingui/macro';
import type { NFTInfo, Wallet } from '@chia/api';
import { useGetNFTWallets } from '@chia/api-react';
import { Grid } from '@mui/material';
import NFTGallerySidebar from './NFTGallerySidebar';
import NFTCard from '../NFTCard';
import Search from './NFTGallerySearch';
import NFTContextualActions from '../NFTContextualActions';
import type NFTSelection from '../../../types/NFTSelection';
import useFetchNFTs from '../../../hooks/useFetchNFTs';

export default function NFTGallery() {
  const { wallets: nftWallets, isLoading: isLoadingWallets } =
    useGetNFTWallets();
  const { nfts, isLoading: isLoadingNFTs } = useFetchNFTs(
    nftWallets.map((wallet: Wallet) => wallet.id),
  );
  const isLoading = isLoadingWallets || isLoadingNFTs;
  const [search, setSearch] = useState<string>('');
  const [walletId, setWalletId] = useState<number | undefined>();
  const t = useTrans();
  const [selection, setSelection] = useState<NFTSelection>({
    items: [],
  });

  const filteredData = useMemo(() => {
    if (!nfts) {
      return nfts;
    }

    return nfts.filter((nft) => {
      const { metadata = {} } = nft;

      if (walletId !== undefined && nft.walletId !== walletId) {
        return false;
      }

      const { name = 'Test' } = metadata;
      if (search) {
        return name.toLowerCase().includes(search.toLowerCase());
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
          : items.filter((item) => item.id !== nft.id),
      };
    });
  }

  if (isLoading) {
    return <Loading center />;
  }

  return (
    <LayoutDashboardSub
      sidebar={<NFTGallerySidebar onWalletChange={setWalletId} />}
      header={(
        <Flex justifyContent="space-between" alignItems="center">
          <Search
            onChange={setSearch}
            value={search}
            placeholder={t(defineMessage({ message: `Search...` }))}
          />
          <NFTContextualActions selection={selection} />
        </Flex>
      )}
    >
      <Grid spacing={2} alignItems="stretch" container>
        {filteredData?.map((nft: NFTInfo) => (
          <Grid xs={12} md={6} lg={4} xl={3} key={nft.id} item>
            <NFTCard
              nft={nft}
              onSelect={(selected) => handleSelect(nft, selected)}
              selected={selection.items.some((item) => item.id === nft.id)}
            />
          </Grid>
        ))}
      </Grid>
    </LayoutDashboardSub>
  );
}
