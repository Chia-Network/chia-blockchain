import React, { useMemo } from 'react';
import { Trans } from '@lingui/macro';
import { WalletType } from '@chia/api';
import { useFormContext, useWatch } from 'react-hook-form';
import type { CATToken, Wallet } from '@chia/api';
import { useGetCatListQuery, useGetWalletsQuery } from '@chia/api-react';
import {
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Typography,
} from '@mui/material';
import useOfferBuilderContext from '../../hooks/useOfferBuilderContext';

export type OfferBuilderTokenSelectorProps = {
  name: string;
  readOnly?: boolean;
  usedAssets?: string[];
};

export default function OfferBuilderTokenSelector(
  props: OfferBuilderTokenSelectorProps,
) {
  const { name, readOnly = false, usedAssets = [] } = props;
  const { usedAssetIds } = useOfferBuilderContext();
  const { setValue } = useFormContext();
  const currentValue = useWatch({ name });
  const { data: wallets = [], isLoading: isLoadingWallets } =
    useGetWalletsQuery();
  const { data: catList = [], isLoading: isLoadingCATs } = useGetCatListQuery();
  const isLoading = isLoadingWallets || isLoadingCATs;

  const [selectedOption, options] = useMemo(() => {
    if (isLoading) {
      return [];
    }

    const allOptions = wallets
      .filter((wallet: Wallet) => wallet.type === WalletType.CAT)
      .map((wallet: Wallet) => {
        const cat: CATToken | undefined = catList.find(
          (cat: CATToken) =>
            cat.assetId.toLowerCase() === wallet.meta?.assetId?.toLowerCase(),
        );

        const assetId = wallet.meta?.assetId.toLowerCase();

        if (
          assetId &&
          assetId !== currentValue &&
          usedAssetIds.includes(assetId)
        ) {
          return undefined;
        }

        return {
          assetId,
          displayName: wallet.name + (cat?.symbol ? ` (${cat.symbol})` : ''),
        };
      })
      .filter(Boolean);

    const selected = allOptions.find(
      (option) => option.assetId.toString() === currentValue,
    );

    return [selected, allOptions];
  }, [isLoading, wallets, catList, currentValue, usedAssets, usedAssetIds]);

  function handleSelection(selection: { assetId: number }) {
    setValue(name, selection.assetId);
  }

  if (readOnly) {
    return (
      <Typography variant="h6" noWrap>
        {selectedOption?.displayName ?? currentValue}
      </Typography>
    );
  }

  return (
    <FormControl variant="filled" fullWidth>
      <InputLabel required focused>
        <Trans>Asset Type</Trans>
      </InputLabel>
      <Select value={currentValue} fullWidth>
        {isLoading ? (
          <MenuItem disabled value={-1}>
            <Trans>Loading...</Trans>
          </MenuItem>
        ) : (
          options.map((option) => (
            <MenuItem
              value={option.assetId}
              key={option.assetId}
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
