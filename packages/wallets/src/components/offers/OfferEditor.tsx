import React, { useState } from 'react';
import BigNumber from 'bignumber.js';
import { useForm } from 'react-hook-form';
import { useNavigate } from 'react-router-dom';
import { useLocalStorage } from '@rehooks/local-storage';
import { Trans, t } from '@lingui/macro';
import {
  Back,
  Button,
  Card,
  ButtonLoading,
  Flex,
  Form,
  useShowError,
  useShowSaveDialog,
} from '@chia/core';
import { useCreateOfferForIdsMutation } from '@chia/api-react';
import {
  Grid,
} from '@mui/material';
import type OfferEditorRowData from './OfferEditorRowData';
import { suggestedFilenameForOffer } from './utils';
import useAssetIdName from '../../hooks/useAssetIdName';
import { WalletType } from '@chia/api';
import OfferEditorConditionsPanel from './OfferEditorConditionsPanel';
import OfferLocalStorageKeys from './OfferLocalStorage';
import { chiaToMojo, catToMojo } from '@chia/core';
import fs from 'fs';


type FormData = {
  selectedTab: number;
  makerRows: OfferEditorRowData[];
  takerRows: OfferEditorRowData[];
  fee: string;
};

type OfferEditorProps = {
  onOfferCreated: (obj: { offerRecord: any, offerData: any }) => void;
};

function OfferEditor(props: OfferEditorProps) {
  const { onOfferCreated } = props;
  const showSaveDialog = useShowSaveDialog();
  const navigate = useNavigate();
  const defaultValues: FormData = {
    selectedTab: 0,
    makerRows: [{ amount: '', assetWalletId: 0, walletType: WalletType.STANDARD_WALLET, spendableBalance: new BigNumber(0) }],
    takerRows: [{ amount: '', assetWalletId: 0, walletType: WalletType.STANDARD_WALLET, spendableBalance: new BigNumber(0) }],
    fee: '',
  };
  const methods = useForm<FormData>({
    defaultValues,
  });
  const errorDialog = useShowError();
  const { lookupByAssetId } = useAssetIdName();
  const [suppressShareOnCreate] = useLocalStorage<boolean>(OfferLocalStorageKeys.SUPPRESS_SHARE_ON_CREATE);
  const [createOfferForIds] = useCreateOfferForIdsMutation();
  const [processing, setIsProcessing] = useState<boolean>(false);

  function updateOffer(offer: { [key: string]: BigNumber }, row: OfferEditorRowData, debit: boolean) {
    const { amount, assetWalletId, walletType } = row;
    if (assetWalletId > 0) {
      let mojoAmount = new BigNumber(0);
      if (walletType === WalletType.STANDARD_WALLET) {
        mojoAmount = chiaToMojo(amount);
      }
      else if (walletType === WalletType.CAT) {
        mojoAmount = catToMojo(amount);
      }

      offer[assetWalletId] = debit
        ? mojoAmount.negated()
        : mojoAmount;
    }
    else {
      console.log('missing asset wallet id');
    }
  }

  async function onSubmit(formData: FormData) {
    const offer: { [key: string]: BigNumber } = {};
    let missingAssetSelection = false;
    let missingAmount = false;
    let amountExceedsSpendableBalance = false;
    let feeInMojos = chiaToMojo(formData.fee ?? 0);

    formData.makerRows.forEach((row: OfferEditorRowData) => {
      updateOffer(offer, row, true);
      if (row.assetWalletId === 0) {
        missingAssetSelection = true;
      }
      else if (!row.amount) {
        missingAmount = true;
      }
      else if (new BigNumber(row.amount).isGreaterThan(row.spendableBalance)) {
        amountExceedsSpendableBalance = true;
      }
    });
    formData.takerRows.forEach((row: OfferEditorRowData) => {
      updateOffer(offer, row, false);
      if (row.assetWalletId === 0) {
        missingAssetSelection = true;
      }
    });

    if (missingAssetSelection || missingAmount || amountExceedsSpendableBalance) {
      if (missingAssetSelection) {
        errorDialog(new Error(t`Please select an asset for each row`));
      }
      else if (missingAmount) {
        errorDialog(new Error(t`Please enter an amount for each row`));
      }
      else if (amountExceedsSpendableBalance) {
        errorDialog(new Error(t`Amount exceeds spendable balance`));
      }

      return;
    }

    setIsProcessing(true);

    try {
      // preflight offer creation to check validity
      const response = await createOfferForIds({ walletIdsAndAmounts: offer, feeInMojos, validateOnly: true }).unwrap();

      if (response.success === false) {
        const error = response.error || new Error("Encountered an unknown error while validating offer");
        errorDialog(error);
      }
      else {
        const dialogOptions = { defaultPath: suggestedFilenameForOffer(response.tradeRecord.summary, lookupByAssetId) };

        const result = await showSaveDialog(dialogOptions);
        console.log('result', result, dialogOptions);
        const { filePath, canceled } = result;

        if (!canceled && filePath) {
          const response = await createOfferForIds({ walletIdsAndAmounts: offer, feeInMojos, validateOnly: false }).unwrap();
          if (response.success === false) {
            const error = response.error || new Error("Encountered an unknown error while creating offer");
            errorDialog(error);
          }
          else {
            const { offer: offerData, tradeRecord: offerRecord } = response;

            try {
              fs.writeFileSync(filePath, offerData);
              navigate(-1);

              if (!suppressShareOnCreate) {
                onOfferCreated({ offerRecord, offerData });
              }
            }
            catch (err) {
              console.error(err);
            }
          }
        }
      }
    }
    catch (e) {
      let error = e as Error;

      if (error.message.startsWith('insufficient funds')) {
        error = new Error(t`
          Insufficient funds available to create offer. Ensure that your
          spendable balance is sufficient to cover the offer amount.
        `);
      }
      errorDialog(error);
    }
    finally {
      setIsProcessing(false);
    }
  }

  function handleReset() {
    methods.reset(defaultValues);
  }

  return (
    <Form methods={methods} onSubmit={onSubmit}>
      <Flex flexDirection="column" rowGap={3} flexGrow={1}>
        <Card>
          <OfferEditorConditionsPanel makerSide="sell" disabled={processing} />
        </Card>
        <Flex justifyContent="flex-end" gap={2}>
          <Button
            variant="outlined"
            type="reset"
            onClick={handleReset}
            disabled={processing}
          >
            <Trans>Reset</Trans>
          </Button>
          <ButtonLoading
            variant="contained"
            color="primary"
            type="submit"
            loading={processing}
          >
            <Trans>Save Offer</Trans>
          </ButtonLoading>
        </Flex>
      </Flex>
    </Form>
  );
}

OfferEditor.defaultProps = {
  onOfferCreated: () => {},
};

type CreateOfferEditorProps = {
  onOfferCreated: (obj: { offerRecord: any, offerData: any }) => void;
};

export function CreateOfferEditor(props: CreateOfferEditorProps) {
  const { onOfferCreated } = props;

  return (
    <Grid container>
      <Flex flexDirection="column" flexGrow={1} gap={3}>
        <Flex>
          <Back variant="h5" to="/dashboard/offers/manage">
            <Trans>Create an Offer</Trans>
          </Back>
        </Flex>
        <OfferEditor onOfferCreated={onOfferCreated}/>
      </Flex>
    </Grid>
  );
}

CreateOfferEditor.defaultProps = {
  onOfferCreated: () => {},
};
