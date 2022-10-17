import React, {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useRef,
} from 'react';
import { useForm } from 'react-hook-form';
import { Form } from '@chia/core';
import { Grid } from '@mui/material';
import OfferBuilderProvider from './OfferBuilderProvider';
import OfferBuilderTradeColumn from './OfferBuilderTradeColumn';
import type OfferBuilderData from '../../@types/OfferBuilderData';

export const emptyDefaultValues = {
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
    fee: [],
  },
};

export type OfferBuilderProps = {
  isMyOffer?: boolean;
  readOnly?: boolean;
  viewer?: boolean;
  onSubmit: (values: OfferBuilderData) => Promise<void>;
  defaultValues?: OfferBuilderData;
};

function OfferBuilder(props: OfferBuilderProps, ref: any) {
  const {
    isMyOffer = false,
    readOnly = false,
    viewer = false,
    defaultValues = emptyDefaultValues,
    onSubmit,
  } = props;

  const formRef = useRef<HTMLFormElement | null>(null);

  const methods = useForm<OfferBuilderData>({
    defaultValues,
  });

  useEffect(() => {
    methods.reset(defaultValues);
  }, [defaultValues, methods]);

  useImperativeHandle(ref, () => ({
    submit: () => {
      if (formRef.current) {
        formRef.current.dispatchEvent(
          new Event('submit', { cancelable: true, bubbles: true }),
        );
      }
    },
  }));

  const offerColumn = (
    <Grid xs={12} md={6} item>
      <OfferBuilderTradeColumn
        name="offered"
        viewer={viewer}
        isMyOffer={isMyOffer}
        offering
      />
    </Grid>
  );
  const requestColumn = (
    <Grid xs={12} md={6} item>
      <OfferBuilderTradeColumn
        name="requested"
        viewer={viewer}
        isMyOffer={isMyOffer}
      />
    </Grid>
  );

  const tradeColumns = [offerColumn, requestColumn];

  if (isMyOffer) {
    tradeColumns.reverse();
  }

  return (
    <Form methods={methods} onSubmit={onSubmit} ref={formRef}>
      <OfferBuilderProvider isMyOffer={isMyOffer} readOnly={readOnly}>
        <Grid spacing={3} rowSpacing={4} container>
          {tradeColumns}
        </Grid>
      </OfferBuilderProvider>
    </Form>
  );
}

export default forwardRef(OfferBuilder);
