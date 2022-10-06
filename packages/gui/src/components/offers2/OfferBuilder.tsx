import React, { forwardRef, useImperativeHandle, useRef } from 'react';
import { useForm } from 'react-hook-form';
import { Form, Loading, useOpenDialog } from '@chia/core';
import { t } from '@lingui/macro';
import { Grid } from '@mui/material';
import OfferEditorConfirmationDialog from '../offers/OfferEditorConfirmationDialog';
import { useNavigate } from 'react-router-dom';
import { useLocalStorage } from '@rehooks/local-storage';
import {
  useCreateOfferForIdsMutation,
  useGetWalletsQuery,
} from '@chia/api-react';
import OfferBuilderProvider from './OfferBuilderProvider';
import OfferBuilderTradeColumn from './OfferBuilderTradeColumn';
import OfferLocalStorageKeys from '../offers/OfferLocalStorage';
import OfferBuilderData from '../../@types/OfferBuilderData';
import offerBuilderDataToOffer from '../../util/offerBuilderDataToOffer';

const defaultValues = {
  offered: {
    xch: [],
    tokens: [],
    nfts: [],
    fee: [],
  },
  requested: {
    xch: [],
    tokens: [],
    nfts: [],
  },
};

export type OfferBuilderProps = {
  readOnly?: boolean;
  onOfferCreated: (obj: { offerRecord: any; offerData: any }) => void;
};

function OfferBuilder(props: OfferBuilderProps, ref: any) {
  const { onOfferCreated, readOnly = false } = props;

  const openDialog = useOpenDialog();
  const navigate = useNavigate();
  const [suppressShareOnCreate] = useLocalStorage<boolean>(
    OfferLocalStorageKeys.SUPPRESS_SHARE_ON_CREATE,
  );
  const formRef = useRef<HTMLFormElement | null>(null);
  const { data: wallets, isLoading } = useGetWalletsQuery();
  const [createOfferForIds] = useCreateOfferForIdsMutation();
  const methods = useForm<OfferBuilderData>({
    defaultValues,
  });

  useImperativeHandle(ref, () => ({
    submit: () => {
      if (formRef.current) {
        formRef.current.dispatchEvent(
          new Event('submit', { cancelable: true, bubbles: true }),
        );
      }
    },
  }));

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

  if (isLoading) {
    return <Loading center />;
  }

  return (
    <Form methods={methods} onSubmit={handleSubmit} ref={formRef}>
      <OfferBuilderProvider readOnly={readOnly}>
        <Grid spacing={3} rowSpacing={4} container>
          <Grid md={6} item>
            <OfferBuilderTradeColumn name="offered" offering />
          </Grid>
          <Grid md={6} item>
            <OfferBuilderTradeColumn name="requested" />
          </Grid>
        </Grid>
      </OfferBuilderProvider>
    </Form>
  );
}

export default forwardRef(OfferBuilder);
