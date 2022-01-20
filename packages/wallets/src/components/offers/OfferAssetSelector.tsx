import React, { useMemo } from 'react';
import { useFormContext } from 'react-hook-form';
import { Wallet, WalletType, type CATToken } from '@chia/api';
import { useGetCatListQuery, useGetWalletsQuery } from '@chia/api-react';
import { Trans } from '@lingui/macro';
import { FormControl, InputLabel, MenuItem } from '@material-ui/core';
import { Select } from '@chia/core';
import type OfferEditorRowData from './OfferEditorRowData';

type WalletOfferAssetSelection = {
  walletId: number;
  walletType: WalletType;
  name: string;
  symbol?: string;
  displayName: string;
  disabled: boolean;
  tail?: string;
};

function buildAssetSelectorList(
  wallets: Wallet[],
  catList: CATToken[],
  rows: OfferEditorRowData[],
  otherRows: OfferEditorRowData[],
  selectedWalletId: number): WalletOfferAssetSelection[]
{
  const list: WalletOfferAssetSelection[] = [];
  const usedWalletIds: Set<number> = new Set();
  const otherUsedWalletIds: Set<number> = new Set();

  rows.map(row => {
    if (row.assetWalletId !== undefined && row.assetWalletId !== selectedWalletId) {
      usedWalletIds.add(row.assetWalletId);
    }
  });

  otherRows.map(row => {
    if (row.assetWalletId !== undefined) {
      otherUsedWalletIds.add(row.assetWalletId);
    }
  });

  wallets.map(wallet => {
    const walletId: number = wallet.id;
    const walletType: WalletType = wallet.type;
    let name: string | undefined;
    let symbol: string | undefined;
    let tail: string | undefined;
    let disabled = false;

    if (usedWalletIds.has(walletId)) {
      return;
    }

    // Disable the selection of wallets that are used by the other side of the trade
    if (otherUsedWalletIds.has(walletId)) {
      disabled = true;
    }

    if (wallet.type === WalletType.STANDARD_WALLET) {
      name = 'Chia';
      symbol = 'XCH';
    }
    else if (wallet.type === WalletType.CAT) {
      name = wallet.name;
      tail = wallet.meta.assetId;
      const cat = catList.find(cat => cat.assetId.toLowerCase() === tail?.toLowerCase());

      if (cat) {
        symbol = cat.symbol;
      }
    }

    if (name) {
      const displayName = name + (symbol ? ` (${symbol})` : '');
      list.push({ walletId, walletType, name, symbol, displayName, disabled, tail });
    }
  });
  return list;
}

type OfferAssetSelectorProps = {
  name: string;
  id: string;
  tradeSide: 'buy' | 'sell';
  defaultValue: any;
  showAddWalletMessage: boolean;
  onChange?: (selectedWalletId: number, selectedWalletType: WalletType) => void;
  disabled?: boolean;
};

function OfferAssetSelector(props: OfferAssetSelectorProps) {
  const { name, id, tradeSide, defaultValue, showAddWalletMessage, onChange, ...rest } = props;
  const { data: wallets, isLoading } = useGetWalletsQuery();
  const { data: catList = [], isLoading: isCatListLoading } = useGetCatListQuery();
  const { getValues, watch } = useFormContext();
  const rows = watch(tradeSide === 'buy' ? 'takerRows' : 'makerRows');
  const otherRows = watch(tradeSide === 'buy' ? 'makerRows' : 'takerRows');
  const selectedWalletId = getValues(id);
  const options: WalletOfferAssetSelection[] = useMemo(() => {
    if (isLoading || isCatListLoading) {
      return [];
    }
    return buildAssetSelectorList(wallets, catList, rows, otherRows, selectedWalletId);
  }, [wallets, catList, rows, otherRows]);

  function handleSelection(selectedWalletId: number, selectedWalletType: WalletType) {
    if (onChange) {
      onChange(selectedWalletId, selectedWalletType);
    }
  }

  return (
    // Form control with popup selection of assets
    <FormControl variant="filled" fullWidth {...rest}>
      <InputLabel required focused>
        <Trans>Asset Type</Trans>
      </InputLabel>
      <Select name={name} id={id} defaultValue={defaultValue || ''}>
        {showAddWalletMessage === true && (
          <MenuItem
            disabled={true}
            value={-1}
            key={-1}
            onClick={() => {}}
          >
            <Trans>Add CAT wallets to have more options</Trans>
          </MenuItem>
        )}
        {options.map((option) => (
          <MenuItem
            disabled={option.disabled}
            value={option.walletId}
            key={option.walletId}
            onClick={() => handleSelection(option.walletId, option.walletType)}
          >
            <Trans>{option.displayName}</Trans>
          </MenuItem>
        ))}
      </Select>
    </FormControl>
  );
}

OfferAssetSelector.defaultProps = {
  showAddWalletMessage: false,
  disabled: false,
}

export default OfferAssetSelector;
