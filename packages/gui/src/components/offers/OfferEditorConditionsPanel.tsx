import React, { useMemo } from 'react';
import BigNumber from 'bignumber.js';
import { useFormContext, useFieldArray } from 'react-hook-form';
import { Trans } from '@lingui/macro';
import {
  Amount,
  Fee,
  Flex,
  TooltipIcon,
  mojoToChia,
  mojoToChiaLocaleString,
  mojoToCAT,
  mojoToCATLocaleString,
  useLocale,
} from '@chia/core';
import { Box, Divider, IconButton, Typography } from '@mui/material';
import { Add, Remove } from '@mui/icons-material';
import { useGetWalletBalanceQuery, useGetWalletsQuery } from '@chia/api-react';
import { Wallet, WalletType } from '@chia/api';
import type OfferEditorRowData from './OfferEditorRowData';
import OfferAssetSelector from './OfferAssetSelector';
import OfferExchangeRate from './OfferExchangeRate';
import useAssetIdName, { AssetIdMapEntry } from '../../hooks/useAssetIdName';

type OfferEditorConditionsRowProps = {
  namePrefix: string;
  item: OfferEditorRowData;
  tradeSide: 'buy' | 'sell'; // section that the row belongs to
  addRow: (() => void) | undefined; // undefined if adding is not allowed
  removeRow: (() => void) | undefined; // undefined if removing is not allowed
  updateRow: (row: OfferEditorRowData) => void;
  showAddWalletMessage: boolean;
  disabled?: boolean;
};

function OfferEditorConditionRow(props: OfferEditorConditionsRowProps) {
  const {
    namePrefix,
    item,
    tradeSide,
    addRow,
    removeRow,
    updateRow,
    showAddWalletMessage,
    disabled,
    ...rest
  } = props;
  const { getValues } = useFormContext();
  const [locale] = useLocale();
  const row: OfferEditorRowData = getValues(namePrefix);
  const { data: walletBalance, isLoading } = useGetWalletBalanceQuery({
    walletId: row.assetWalletId,
  });

  const spendableBalanceString: string | undefined = useMemo(() => {
    let balanceString: string | undefined;
    let balance = new BigNumber(0);

    if (
      !isLoading &&
      tradeSide === 'sell' &&
      walletBalance &&
      walletBalance.walletId == row.assetWalletId
    ) {
      switch (item.walletType) {
        case WalletType.STANDARD_WALLET:
          balanceString = mojoToChiaLocaleString(
            walletBalance.spendableBalance,
            locale,
          );
          balance = mojoToChia(walletBalance.spendableBalance);
          break;
        case WalletType.CAT:
          balanceString = mojoToCATLocaleString(
            walletBalance.spendableBalance,
            locale,
          );
          balance = mojoToCAT(walletBalance.spendableBalance);
          break;
        default:
          break;
      }
    }

    if (
      balanceString !== row.spendableBalanceString ||
      !balance.isEqualTo(row.spendableBalance)
    ) {
      row.spendableBalanceString = balanceString;
      row.spendableBalance = balance;

      updateRow(row);
    }

    return balanceString;
  }, [row.assetWalletId, walletBalance, isLoading, locale]);

  function handleAssetChange(
    namePrefix: string,
    selectedWalletId: number,
    selectedWalletType: WalletType,
  ) {
    const row: OfferEditorRowData = getValues(namePrefix);

    row.assetWalletId = selectedWalletId;
    row.walletType = selectedWalletType;
    row.spendableBalanceString = spendableBalanceString;
    row.spendableBalance = walletBalance
      ? new BigNumber(walletBalance.spendableBalance)
      : new BigNumber(0);

    updateRow(row);
  }

  function handleAmountChange(namePrefix: string, amount: string) {
    const row: OfferEditorRowData = getValues(namePrefix);

    updateRow({
      ...row,
      amount,
    });
  }

  return (
    <Flex flexDirection="row" gap={0} {...rest}>
      <Flex flexDirection="row" gap={0} style={{ width: '90%' }}>
        <Flex flexDirection="column" flexGrow={1} style={{ width: '45%' }}>
          <OfferAssetSelector
            name={`${namePrefix}.assetWalletId`}
            id={`${namePrefix}.assetWalletId`}
            tradeSide={tradeSide}
            defaultValue={undefined}
            onChange={(walletId: number, walletType: WalletType) =>
              handleAssetChange(namePrefix, walletId, walletType)
            }
            showAddWalletMessage={showAddWalletMessage}
            disabled={disabled}
          />
        </Flex>
        <Flex style={{ width: '2em' }}>
          {/* Spacing to accommodate center alignment of the OfferExchangeRate component rendered externally */}
        </Flex>
        <Flex flexDirection="column" flexGrow={1} style={{ width: '45%' }}>
          <Flex flexDirection="column" gap={1}>
            <Amount
              variant="filled"
              color="secondary"
              label={<Trans>Amount</Trans>}
              id={`${namePrefix}.amount`}
              name={`${namePrefix}.amount`}
              disabled={disabled}
              symbol={
                item.walletType === WalletType.STANDARD_WALLET ? undefined : ''
              }
              showAmountInMojos={item.walletType === WalletType.STANDARD_WALLET}
              onChange={(value: string) =>
                handleAmountChange(namePrefix, value)
              }
              required
              fullWidth
            />
            {tradeSide === 'sell' && row.assetWalletId > 0 && (
              <Flex flexDirection="row" alignItems="center" gap={1}>
                <Typography variant="body2">Spendable balance: </Typography>
                {spendableBalanceString === undefined ? (
                  <Typography variant="body2">Loading...</Typography>
                ) : (
                  <Typography variant="body2">
                    {spendableBalanceString}
                  </Typography>
                )}
              </Flex>
            )}
          </Flex>
        </Flex>
      </Flex>
      <Flex flexDirection="column" flexGrow={1} style={{ width: '10%' }}>
        <Flex
          flexDirection="row"
          justifyContent="top"
          alignItems="flex-start"
          gap={0.5}
          style={{ paddingTop: '0.25em' }}
        >
          <IconButton
            aria-label="remove"
            onClick={removeRow}
            disabled={disabled || !removeRow}
          >
            <Remove />
          </IconButton>
          <IconButton
            aria-label="add"
            onClick={addRow}
            disabled={disabled || !addRow}
          >
            <Add />
          </IconButton>
        </Flex>
      </Flex>
    </Flex>
  );
}

OfferEditorConditionRow.defaultProps = {
  showAddWalletMessage: false,
  disabled: false,
};

type OfferEditorConditionsPanelProps = {
  makerSide: 'buy' | 'sell';
  disabled?: boolean;
};

function OfferEditorConditionsPanel(props: OfferEditorConditionsPanelProps) {
  const { makerSide, disabled } = props;
  const { control } = useFormContext();
  const {
    fields: makerFields,
    append: makerAppend,
    remove: makerRemove,
    update: makerUpdate,
  } = useFieldArray({
    control,
    name: 'makerRows',
  });
  const {
    fields: takerFields,
    append: takerAppend,
    remove: takerRemove,
    update: takerUpdate,
  } = useFieldArray({
    control,
    name: 'takerRows',
  });
  const { data: wallets, isLoading }: { data: Wallet[]; isLoading: boolean } =
    useGetWalletsQuery();
  const { watch } = useFormContext();
  const { lookupByWalletId } = useAssetIdName();
  const makerRows: OfferEditorRowData[] = watch('makerRows');
  const takerRows: OfferEditorRowData[] = watch('takerRows');

  const { canAddMakerRow, canAddTakerRow } = useMemo(() => {
    let canAddMakerRow = false;
    let canAddTakerRow = false;

    if (!isLoading) {
      const makerWalletIds: Set<number> = new Set();
      const takerWalletIds: Set<number> = new Set();
      makerRows.forEach((makerRow) => {
        if (makerRow.assetWalletId > 0) {
          makerWalletIds.add(makerRow.assetWalletId);
        }
      });
      takerRows.forEach((takerRow) => {
        if (takerRow.assetWalletId > 0) {
          takerWalletIds.add(takerRow.assetWalletId);
        }
      });
      canAddMakerRow =
        makerWalletIds.size < wallets.length &&
        makerRows.length < wallets.length &&
        makerRows.length + takerRows.length < wallets.length;
      canAddTakerRow =
        takerWalletIds.size < wallets.length &&
        takerRows.length < wallets.length &&
        makerRows.length + takerRows.length < wallets.length;
    }

    return { canAddMakerRow, canAddTakerRow };
  }, [wallets, isLoading, makerRows, takerRows]);

  const {
    makerAssetInfo,
    makerExchangeRate,
    takerAssetInfo,
    takerExchangeRate,
  } = useMemo(() => {
    let makerAssetInfo: AssetIdMapEntry | undefined = undefined;
    let takerAssetInfo: AssetIdMapEntry | undefined = undefined;
    let makerExchangeRate: number | undefined = undefined;
    let takerExchangeRate: number | undefined = undefined;

    if (!isLoading && makerRows.length === 1 && takerRows.length === 1) {
      const makerWalletId: string | undefined =
        makerRows[0].assetWalletId > 0
          ? makerRows[0].assetWalletId.toString()
          : undefined;
      const takerWalletId: string | undefined =
        takerRows[0].assetWalletId > 0
          ? takerRows[0].assetWalletId.toString()
          : undefined;

      if (makerWalletId && takerWalletId) {
        makerAssetInfo = lookupByWalletId(makerWalletId);
        takerAssetInfo = lookupByWalletId(takerWalletId);
        makerExchangeRate =
          Number(takerRows[0].amount) / Number(makerRows[0].amount);
        takerExchangeRate =
          Number(makerRows[0].amount) / Number(takerRows[0].amount);
      }
    }

    return {
      makerAssetInfo,
      makerExchangeRate,
      takerAssetInfo,
      takerExchangeRate,
    };
  }, [isLoading, makerRows, takerRows]);

  type Section = {
    side: 'buy' | 'sell';
    fields: any[];
    canAddRow: boolean;
    namePrefix: string;
    headerTitle?: React.ReactElement;
  };
  const sections: Section[] = [
    {
      side: 'buy',
      fields: takerFields,
      namePrefix: 'takerRows',
      canAddRow: canAddTakerRow,
    },
    {
      side: 'sell',
      fields: makerFields,
      namePrefix: 'makerRows',
      canAddRow: canAddMakerRow,
    },
  ];
  const showAddCATsMessage = !canAddTakerRow && wallets?.length === 1;
  const showExchangeRate = !!makerAssetInfo && !!takerAssetInfo;

  if (makerSide === 'sell') {
    sections.reverse();
  }

  sections[0].headerTitle = <Trans>You will offer</Trans>;
  sections[1].headerTitle = <Trans>In exchange for</Trans>;

  function exchangeRateChanged(
    updatedExchangeRate: string | number,
    side: 'maker' | 'taker',
  ) {
    const rate = Number(updatedExchangeRate);
    const amount = Number(
      side === 'taker' ? makerRows[0].amount : takerRows[0].amount,
    );
    const haveAmount: boolean = amount > 0 && Number.isFinite(amount);
    const assetInfo: AssetIdMapEntry | undefined =
      side === 'maker' ? makerAssetInfo : takerAssetInfo;
    const newAmount = Number(
      haveAmount ? rate * amount : updatedExchangeRate,
    ).toFixed(assetInfo?.walletType === WalletType.STANDARD_WALLET ? 9 : 12);
    if (side === 'taker') {
      takerUpdate(0, { ...takerRows[0], amount: newAmount });
      if (!haveAmount) {
        makerUpdate(0, { ...makerRows[0], amount: 1 });
      }
    } else {
      makerUpdate(0, { ...makerRows[0], amount: newAmount });
      if (!haveAmount) {
        takerUpdate(0, { ...takerRows[0], amount: 1 });
      }
    }
  }

  return (
    <Flex flexDirection="column" gap={3}>
      {sections.map((section, sectionIndex) => (
        <Flex flexDirection="column" gap={2} key={sectionIndex}>
          <Typography variant="subtitle1">{section.headerTitle}</Typography>
          {section.fields.map((field, fieldIndex) => (
            <OfferEditorConditionRow
              key={fieldIndex}
              namePrefix={`${section.namePrefix}[${fieldIndex}]`}
              item={field}
              tradeSide={section.side}
              addRow={
                section.canAddRow
                  ? () => {
                      section.side === 'buy'
                        ? takerAppend({
                            amount: '',
                            assetWalletId: '',
                            walletType: WalletType.STANDARD_WALLET,
                          })
                        : makerAppend({
                            amount: '',
                            assetWalletId: '',
                            walletType: WalletType.STANDARD_WALLET,
                          });
                    }
                  : undefined
              }
              removeRow={
                section.fields.length > 1
                  ? () => {
                      section.side === 'buy'
                        ? takerRemove(fieldIndex)
                        : makerRemove(fieldIndex);
                    }
                  : undefined
              }
              updateRow={(updatedRow: OfferEditorRowData) => {
                section.side === 'buy'
                  ? takerUpdate(fieldIndex, updatedRow)
                  : makerUpdate(fieldIndex, updatedRow);
              }}
              showAddWalletMessage={
                section.side === 'buy' && showAddCATsMessage
              }
              disabled={disabled}
            />
          ))}
          {sectionIndex !== sections.length - 1 && <Divider />}
        </Flex>
      ))}
      {showExchangeRate && (
        <>
          <Divider />
          <Flex flexDirection="row" gap={0}>
            <Flex flexDirection="column" style={{ width: '90%' }}>
              <OfferExchangeRate
                readOnly={false}
                makerAssetInfo={makerAssetInfo}
                makerExchangeRate={makerExchangeRate}
                takerAssetInfo={takerAssetInfo}
                takerExchangeRate={takerExchangeRate}
                takerExchangeRateChanged={(rate) =>
                  exchangeRateChanged(rate, 'taker')
                }
                makerExchangeRateChanged={(rate) =>
                  exchangeRateChanged(rate, 'maker')
                }
              />
            </Flex>
            {/* 10% reserved for the end to align with the - + buttons in OfferEditorConditionRow */}
            <Flex
              flexDirection="column"
              alignItems="center"
              style={{ width: '10%' }}
            ></Flex>
          </Flex>
        </>
      )}
      <Divider />
      <Flex flexDirection="row" gap={0} style={{ width: '90%' }}>
        <Flex flexDirection="column" flexGrow={1} style={{ width: '45%' }}>
          <Fee
            id="filled-secondary"
            variant="filled"
            name="fee"
            color="secondary"
            label={<Trans>Fee (Optional)</Trans>}
          />
        </Flex>
        <Flex style={{ width: '2em' }} justifyContent="center">
          <Box style={{ position: 'relative', top: '20px' }}>
            <TooltipIcon>
              <Trans>
                Including a fee in the offer can help expedite the transaction
                when the offer is accepted. The recommended minimum fee is
                0.000005 XCH (5,000,000 mojos)
              </Trans>
            </TooltipIcon>
          </Box>
        </Flex>
        <Flex
          flexDirection="column"
          flexGrow={1}
          style={{ width: '45%' }}
        ></Flex>
      </Flex>
    </Flex>
  );
}

OfferEditorConditionsPanel.defaultProps = {
  disabled: false,
};

export default OfferEditorConditionsPanel;
