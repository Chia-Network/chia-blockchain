import React, { useState } from 'react';
import { useForm } from 'react-hook-form';
import { useNavigate } from 'react-router-dom';
import { useLocalStorage } from '@rehooks/local-storage';
import { Trans, t } from '@lingui/macro';
import {
  Back,
  ButtonLoading,
  Flex,
  Form,
  useOpenDialog,
  useShowError,
  useShowSaveDialog,
} from '@chia/core';
import { useCreateOfferForIdsMutation } from '@chia/api-react';
import {
  Button,
  Divider,
  Grid,
} from '@material-ui/core';
import type OfferEditorRowData from './OfferEditorRowData';
import { suggestedFilenameForOffer } from './utils';
import useAssetIdName from '../../hooks/useAssetIdName';
import { WalletType } from '@chia/api';
import OfferEditorConditionsPanel from './OfferEditorConditionsPanel';
import OfferShareDialog from './OfferShareDialog';
import OfferLocalStorageKeys from './OfferLocalStorage';
import styled from 'styled-components';
import { chiaToMojo, catToMojo } from '@chia/core';
import fs from 'fs';
import { Remote } from 'electron';

const StyledEditorBox = styled.div`
  padding: ${({ theme }) => `${theme.spacing(4)}px`};
`;

type FormData = {
  selectedTab: number;
  makerRows: OfferEditorRowData[];
  takerRows: OfferEditorRowData[];
};

function OfferEditor() {
  const showSaveDialog = useShowSaveDialog();
  const navigate = useNavigate();
  const defaultValues: FormData = {
    selectedTab: 0,
    makerRows: [{ amount: '', assetWalletId: undefined, walletType: WalletType.STANDARD_WALLET }],
    takerRows: [{ amount: '', assetWalletId: undefined, walletType: WalletType.STANDARD_WALLET }],
  };
  const methods = useForm<FormData>({
    shouldUnregister: false,
    defaultValues,
  });
  const openDialog = useOpenDialog();
  const errorDialog = useShowError();
  const { lookupByAssetId } = useAssetIdName();
  const [suppressShareOnCreate] = useLocalStorage<boolean>(OfferLocalStorageKeys.SUPPRESS_SHARE_ON_CREATE);
  const [createOfferForIds] = useCreateOfferForIdsMutation();
  const [processing, setIsProcessing] = useState<boolean>(false);

  function updateOffer(offer: { [key: string]: number | string }, row: OfferEditorRowData, debit: boolean) {
    const { amount, assetWalletId, walletType } = row;
    if (assetWalletId) {
      let mojoAmount = 0;
      if (walletType === WalletType.STANDARD_WALLET) {
        mojoAmount = Number.parseFloat(chiaToMojo(amount));
      }
      else if (walletType === WalletType.CAT) {
        mojoAmount = Number.parseFloat(catToMojo(amount));
      }
      offer[assetWalletId] = debit ? -mojoAmount : mojoAmount;
    }
    else {
      console.log('missing asset wallet id');
    }
  }

  async function onSubmit(formData: FormData) {
    const offer: { [key: string]: number | string } = {};
    let missingAssetSelection = false;
    let missingAmount = false;
    let amountExceedsSpendableBalance = false;

    formData.makerRows.forEach((row: OfferEditorRowData) => {
      updateOffer(offer, row, true);
      if (!row.assetWalletId) {
        missingAssetSelection = true;
      }
      else if (!row.amount) {
        missingAmount = true;
      }
      else if (Number.parseFloat(row.amount as string) > row.spendableBalance) {
        amountExceedsSpendableBalance = true;
      }
    });
    formData.takerRows.forEach((row: OfferEditorRowData) => {
      updateOffer(offer, row, false);
      if (!row.assetWalletId) {
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
      const response = await createOfferForIds({ walletIdsAndAmounts: offer, validateOnly: true }).unwrap();

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
          const response = await createOfferForIds({ walletIdsAndAmounts: offer, validateOnly: false }).unwrap();
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
                openDialog((
                  <OfferShareDialog
                    offerRecord={offerRecord}
                    offerData={offerData}
                    showSuppressionCheckbox={true}
                  />
                ));
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
    methods.reset();
  }

  return (
    <Form methods={methods} onSubmit={onSubmit}>
      <Divider />
      <StyledEditorBox>
        <Flex flexDirection="column" rowGap={3} flexGrow={1}>
          <OfferEditorConditionsPanel makerSide="sell" disabled={processing} />
          <Flex gap={3}>
            <Button
              variant="contained"
              color="secondary"
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
      </StyledEditorBox>
    </Form>
  );
}

export function CreateOfferEditor() {
  return (
    <Grid container>
      <Flex flexDirection="column" flexGrow={1} gap={3}>
        <Flex>
          <Back variant="h5" to="/dashboard/wallets/offers/manage">
            <Trans>Create an Offer</Trans>
          </Back>
        </Flex>
        <OfferEditor />
      </Flex>
    </Grid>
  );
}
