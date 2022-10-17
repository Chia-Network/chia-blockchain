import React, { useRef, useMemo } from 'react';
import { t, Trans } from '@lingui/macro';
import {
  useGetWalletsQuery,
  useCreateOfferForIdsMutation,
} from '@chia/api-react';
import { Flex, ButtonLoading, useOpenDialog, Loading } from '@chia/core';
import { Grid } from '@mui/material';
import { useLocalStorage } from '@rehooks/local-storage';
import OfferLocalStorageKeys from '../offers/OfferLocalStorage';
import OfferEditorConfirmationDialog from '../offers/OfferEditorConfirmationDialog';
import { useNavigate } from 'react-router-dom';
import OfferBuilder, { emptyDefaultValues } from './OfferBuilder';
import OfferNavigationHeader from './OfferNavigationHeader';
import offerBuilderDataToOffer from '../../util/offerBuilderDataToOffer';
import type OfferBuilderData from '../../@types/OfferBuilderData';

export type CreateOfferBuilderProps = {
  nftId?: string;
  referrerPath?: string;
  onOfferCreated: (obj: { offerRecord: any; offerData: any }) => void;
};

export default function CreateOfferBuilder(props: CreateOfferBuilderProps) {
  const { referrerPath, onOfferCreated, nftId } = props;

  const openDialog = useOpenDialog();
  const navigate = useNavigate();
  const { data: wallets, isLoading } = useGetWalletsQuery();
  const [createOfferForIds] = useCreateOfferForIdsMutation();
  const offerBuilderRef = useRef<{ submit: () => void } | undefined>(undefined);

  const defaultValues = useMemo(() => {
    if (nftId) {
      return {
        ...emptyDefaultValues,
        offered: {
          ...emptyDefaultValues.offered,
          nfts: [{ nftId }],
        },
      };
    }

    return emptyDefaultValues;
  }, [nftId]);

  const [suppressShareOnCreate] = useLocalStorage<boolean>(
    OfferLocalStorageKeys.SUPPRESS_SHARE_ON_CREATE,
  );

  function handleCreateOffer() {
    offerBuilderRef.current?.submit();
  }

  async function handleSubmit(values: OfferBuilderData) {
    const offer = await offerBuilderDataToOffer(values, wallets, false);

    const confirmedCreation = await openDialog(
      <OfferEditorConfirmationDialog />,
    );

    if (!confirmedCreation) {
      return;
    }

    try {
      const response = await createOfferForIds({
        ...offer,
        disableJSONFormatting: true,
      }).unwrap();

      const { offer: offerData, tradeRecord: offerRecord } = response;

      navigate(-1);

      if (!suppressShareOnCreate) {
        onOfferCreated({ offerRecord, offerData });
      }
    } catch (error) {
      if ((error as Error).message.startsWith('insufficient funds')) {
        throw new Error(t`
          Insufficient funds available to create offer. Ensure that your
          spendable balance is sufficient to cover the offer amount.
        `);
      } else {
        throw error;
      }
    }
  }

  return (
    <Grid container>
      <Flex flexDirection="column" flexGrow={1} gap={4}>
        <Flex alignItems="center" justifyContent="space-between" gap={2}>
          <OfferNavigationHeader referrerPath={referrerPath} />
          <ButtonLoading
            variant="contained"
            color="primary"
            onClick={handleCreateOffer}
            disableElevation
          >
            <Trans>Create Offer</Trans>
          </ButtonLoading>
        </Flex>

        {isLoading ? (
          <Loading center />
        ) : (
          <OfferBuilder
            onSubmit={handleSubmit}
            defaultValues={defaultValues}
            ref={offerBuilderRef}
          />
        )}
      </Flex>
    </Grid>
  );
}
