import React, { useMemo } from 'react';
import { Trans } from '@lingui/macro';
import { WalletType } from '@chia/api';
import type { CATToken, Wallet } from '@chia/api';
import { useGetCatListQuery, useGetWalletsQuery } from '@chia/api-react';
import { useCurrencyCode } from '@chia/core';
import { FormControl, InputLabel, MenuItem, Select } from '@mui/material';

type TokenSelectOption = {
  walletId: number;
  walletType: WalletType;
  name: string;
  symbol?: string;
  displayName: string;
  disabled: boolean;
  tail?: string;
};

type Props = {
  selectedWalletId: number;
  id: string;
  onChange: ({
    walletId,
    walletType,
    symbol,
    name,
  }: {
    walletId: number;
    walletType: WalletType;
    symbol?: string;
    name?: string;
  }) => void;
};

export default function NFTOfferTokenSelector(props: Props) {
  const { selectedWalletId, id, onChange } = props;
  const { data: wallets, isLoadingWallets } = useGetWalletsQuery();
  const { data: catList = [], isLoading: isLoadingCATs } = useGetCatListQuery();
  const isLoading = isLoadingWallets || isLoadingCATs;
  const currencyCode: string = useCurrencyCode();

  const [, options]: [TokenSelectOption, TokenSelectOption[]] = useMemo(() => {
    if (isLoading) {
      return [];
    }

    const chiaWalletSelection = [
      wallets.find(
        (wallet: Wallet) => wallet.type === WalletType.STANDARD_WALLET,
      ),
    ].map((wallet: WalletType) => {
      return {
        walletId: wallet.id,
        walletType: wallet.type,
        name: 'Chia',
        symbol: currencyCode,
        displayName: `Chia (${currencyCode})`,
        disabled: false,
        tail: '',
      };
    });
    const catOptions = wallets
      .filter((wallet: Wallet) => wallet.type === WalletType.CAT)
      .map((wallet: Wallet) => {
        const cat: CATToken | undefined = catList.find(
          (cat: CATToken) =>
            cat.assetId.toLowerCase() === wallet.tail?.toLowerCase(),
        );
        return {
          walletId: wallet.id,
          walletType: wallet.type,
          name: wallet.name,
          symbol: cat?.symbol,
          displayName: wallet.name + (cat?.symbol ? ` (${cat.symbol})` : ''),
          disabled: false,
          tail: wallet.tail,
        };
      });
    const allOptions = [...chiaWalletSelection, ...catOptions];
    const selected = allOptions.find(
      (option: TokenSelectOption) => option.walletId === selectedWalletId,
    );

    return [selected, allOptions];
  }, [catList, currencyCode, selectedWalletId]);

  function handleSelection(selection: TokenSelectOption) {
    onChange({
      walletId: selection.walletId,
      walletType: selection.walletType,
      symbol: selection.symbol,
      name: selection.name,
    });
  }

  return (
    <FormControl variant="filled" fullWidth>
      <InputLabel required focused>
        <Trans>Asset Type</Trans>
      </InputLabel>
      <Select value={selectedWalletId} id={id}>
        {isLoading ? (
          <MenuItem disabled value={-1} key={-1} onClick={() => {}}>
            <Trans>Loading...</Trans>
          </MenuItem>
        ) : (
          options.map((option: TokenSelectOption) => (
            <MenuItem
              value={option.walletId}
              key={option.walletId}
              onClick={() => handleSelection(option)}
            >
              {option.displayName}
            </MenuItem>
          ))
        )}
      </Select>
    </FormControl>
  );
}
