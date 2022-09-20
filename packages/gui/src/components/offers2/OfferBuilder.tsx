import React from 'react';
import { useForm } from 'react-hook-form';
import { Form } from '@chia/core';
import { Grid } from '@mui/material';
import OfferBuilderProvider from './OfferBuilderContext';
import OfferBuilderTradeColumn from './OfferBuilderTradeColumn';
import OfferBuilderTradeSide from './OfferBuilderTradeSide';

type OfferBuilderFormData = {
  offered: {
    xch: {
      amount: string;
    };
    tokens: [];
    nfts: [];
    fee: string;
  };
  requested: {
    xch: {
      amount: string;
    };
    tokens: [];
    nfts: [];
  };
};

function getDefaultValues(): OfferBuilderFormData {
  return {
    offered: {
      xch: {
        amount: '1,234',
      },
      tokens: [],
      nfts: [],
      fee: '',
    },
    requested: {
      xch: {
        amount: '4,321',
      },
      tokens: [],
      nfts: [],
    },
  };
}

export enum OfferBuilderMode {
  Building = 'building',
  Viewing = 'viewing',
}

export type OfferBuilderProps = {
  onOfferCreated: (obj: { offerRecord: any; offerData: any }) => void;
};

export default function OfferBuilder(props: OfferBuilderProps): JSX.Element {
  const { onOfferCreated } = props;
  const methods = useForm<OfferBuilderFormData>({
    defaultValues: getDefaultValues(),
  });
  const mode = OfferBuilderMode.Building; // TODO: make this a prop

  return (
    <OfferBuilderProvider>
      <Form methods={methods}>
        <Grid spacing={4} container>
          <Grid item sm={6}>
            <OfferBuilderTradeColumn
              mode={mode}
              side={OfferBuilderTradeSide.Offering}
              formNamePrefix={'offered'}
            />
          </Grid>
          <Grid item sm={6}>
            <OfferBuilderTradeColumn
              mode={mode}
              side={OfferBuilderTradeSide.Requesting}
              formNamePrefix={'requested'}
            />
          </Grid>
        </Grid>
      </Form>
    </OfferBuilderProvider>
  );
}
