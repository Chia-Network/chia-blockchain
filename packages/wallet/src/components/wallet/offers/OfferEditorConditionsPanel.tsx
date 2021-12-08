import React, { useMemo } from 'react';
import { useFormContext, useFieldArray } from 'react-hook-form';
import { Trans } from '@lingui/macro';
import { Amount, Flex, TextFieldNumber } from '@chia/core';
import { Divider, Grid, IconButton, Typography } from '@material-ui/core';
import { Add, Remove } from '@material-ui/icons';
import { useGetWalletsQuery } from '@chia/api-react';
import { Wallet } from '@chia/api';
import type OfferRowData from './OfferRowData';
import WalletType from '../../../constants/WalletType';
import OfferAssetSelector from './OfferAssetSelector';

type OfferEditorConditionsRowProps = {
  namePrefix: string;
  item: OfferRowData;
  tradeSide: 'buy' | 'sell';  // section that the row belongs to
  addRow: (() => void) | undefined;  // undefined if adding is not allowed
  removeRow: (() => void) | undefined;  // undefined if removing is not allowed
  disabled?: boolean;
};

function OfferEditorConditionRow(props: OfferEditorConditionsRowProps) {
  const { namePrefix, item, tradeSide, addRow, removeRow, disabled, ...rest } = props;
  const { getValues, setValue } = useFormContext();

  function handleAssetChange(namePrefix: string, selectedWalletId: number, selectedWalletType: WalletType) {
    item.walletType = selectedWalletType;
    item.amount = getValues(`${namePrefix}.amount`);  // Stash the amount so that we can set the defaultValue when rendering the amount field
    setValue(`${namePrefix}.walletType`, selectedWalletType);
  }

  return (
    <Flex flexDirection="row" gap={3} {...rest}>
      <Grid xs={6} item>
        <OfferAssetSelector
          name={`${namePrefix}.assetWalletId`}
          id={`${namePrefix}.assetWalletId`}
          tradeSide={tradeSide}
          defaultValue={undefined}
          onChange={(walletId: number, walletType: WalletType) => handleAssetChange(namePrefix, walletId, walletType)}
          disabled={disabled}
        />
      </Grid>
      <Grid xs={6} item>
        {item.walletType === WalletType.STANDARD_WALLET && (
          <Amount
            variant="filled"
            color="secondary"
            label={<Trans>Amount</Trans>}
            defaultValue={item.amount}
            id={`${namePrefix}.amount`}
            name={`${namePrefix}.amount`}
            disabled={disabled}
            required
            fullWidth
          />
        )}
        {item.walletType === WalletType.CAT && (
          <TextFieldNumber
            variant="filled"
            color="secondary"
            label={<Trans>Amount</Trans>}
            defaultValue={item.amount}
            id={`${namePrefix}.amount`}
            name={`${namePrefix}.amount`}
            disabled={disabled}
            required
            fullWidth
          />
        )}
      </Grid>
      <Flex flexDirection="row" justifyContent="top" alignItems="flex-start" gap={0.5} style={{paddingTop: '0.25em'}}>
        <IconButton aria-label="remove" onClick={removeRow} disabled={disabled || !removeRow}>
          <Remove />
        </IconButton>
        <IconButton aria-label="add" onClick={addRow} disabled={disabled || !addRow}>
          <Add />
        </IconButton>
      </Flex>
    </Flex>
  );
}

OfferEditorConditionRow.defaultProps = {
  disabled: false,
};

type OfferEditorConditionsPanelProps = {
  makerSide: 'buy' | 'sell';
  disabled?: boolean;
};

function OfferEditorConditionsPanel(props: OfferEditorConditionsPanelProps) {
  const { makerSide, disabled } = props;
  const { control } = useFormContext();
  const { fields: makerFields, append: makerAppend, remove: makerRemove } = useFieldArray({
    control,
    name: 'makerRows',
  });
  const { fields: takerFields, append: takerAppend, remove: takerRemove } = useFieldArray({
    control,
    name: 'takerRows',
  });
  const { data: wallets, isLoading }: { data: Wallet[], isLoading: boolean} = useGetWalletsQuery();
  const { watch } = useFormContext();
  const makerRows: OfferRowData[] = watch('makerRows');
  const takerRows: OfferRowData[] = watch('takerRows');

  const { canAddMakerRow, canAddTakerRow } = useMemo(() => {
    let canAddMakerRow = false;
    let canAddTakerRow = false;

    if (!isLoading) {
      let makerWalletIds: Set<number> = new Set();
      let takerWalletIds: Set<number> = new Set();
      makerRows.forEach((makerRow) => {
        if (makerRow.assetWalletId) {
          makerWalletIds.add(makerRow.assetWalletId);
        }
      });
      takerRows.forEach((takerRow) => {
        if (takerRow.assetWalletId) {
          takerWalletIds.add(takerRow.assetWalletId);
        }
      });
      canAddMakerRow = makerWalletIds.size < wallets.length && makerRows.length < wallets.length && (makerRows.length + takerRows.length) < wallets.length;
      canAddTakerRow = takerWalletIds.size < wallets.length && takerRows.length < wallets.length && (makerRows.length + takerRows.length) < wallets.length;
    }

    return { canAddMakerRow, canAddTakerRow };
  }, [wallets, isLoading, makerRows, takerRows]);

  type Section = {
    side: 'buy' | 'sell';
    fields: any[];
    canAddRow: boolean;
    namePrefix: string;
    headerTitle?: React.ReactElement;
  };
  const sections: Section[] = [
    { side: 'buy', fields: takerFields, namePrefix: 'takerRows', canAddRow: canAddTakerRow },
    { side: 'sell', fields: makerFields, namePrefix: 'makerRows', canAddRow: canAddMakerRow },
  ];

  if (makerSide === 'sell') {
    sections.reverse();
  }

  // sections[0].headerTitle = sections[0].side === 'buy' ? <Trans>You will buy</Trans> : <Trans>You will sell</Trans>;
  sections[0].headerTitle = <Trans>You will offer</Trans>;
  sections[1].headerTitle = <Trans>In exchange for</Trans>

  return (
    <Flex flexDirection="column" gap={3}>
      {sections.map((section, sectionIndex) => (
        <>
          <Typography variant="h6">{section.headerTitle}</Typography>
          {section.fields.map((field, fieldIndex) => (
            <OfferEditorConditionRow
              key={field.id}
              namePrefix={`${section.namePrefix}[${fieldIndex}]`}
              item={field}
              tradeSide={section.side}
              addRow={section.canAddRow ? (() => { section.side === 'buy' ? takerAppend({ amount: '', assetWalletId: '', walletType: WalletType.STANDARD_WALLET }) : makerAppend({ amount: '', assetWalletId: '', walletType: WalletType.STANDARD_WALLET }) }) : undefined }
              removeRow={
                section.fields.length > 1 ?
                  () => { section.side === 'buy' ? takerRemove(fieldIndex) : makerRemove(fieldIndex) } :
                  undefined
              }
              disabled={disabled}
            />
          ))}
          {sectionIndex !== (sections.length - 1) && (
            <Divider />
          )}
        </>
      ))}
    </Flex>
  );
}

OfferEditorConditionsPanel.defaultProps = {
  disabled: false,
};

export default OfferEditorConditionsPanel;