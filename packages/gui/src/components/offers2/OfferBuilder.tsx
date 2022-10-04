import React from 'react';
import { useForm } from 'react-hook-form';
import { Form } from '@chia/core';
import { Grid } from '@mui/material';
import OfferBuilderProvider from './OfferBuilderProvider';
import OfferBuilderTradeColumn from './OfferBuilderTradeColumn';

type OfferBuilderFormData = {
  offered: {
    xch: {
      amount: string;
    }[];
    tokens: {
      amount: string;
      assetId: string;
    }[];
    nfts: {
      nftId: string;
    }[];
    fee: {
      amount: string;
    }[];
  };
  requested: {
    xch: {
      amount: string;
    }[];
    tokens: {
      amount: string;
      assetId: string;
    }[];
    nfts: {
      nftId: string;
    }[];
  };
};

const mockedDefaultValue = {
  offered: {
    xch: [
      {
        amount: '0.3',
      },
    ],
    tokens: [
      {
        amount: '1',
        assetId:
          '6d95dae356e32a71db5ddcb42224754a02524c615c5fc35f568c2af04774e589',
      },
      {
        amount: '2',
        assetId:
          'a628c1c2c6fcb74d53746157e438e108eab5c0bb3e5c80ff9b1910b3e4832913',
      },
      {
        amount: '3',
        assetId:
          '8ebf855de6eb146db5602f0456d2f0cbe750d57f821b6f91a8592ee9f1d4cf31',
      },
    ],
    nfts: [
      {
        nftId: 'nft1049g9t9ts9qrc9nsd7ta0kez847le6wz59d28zrkrmhj8xu7ucgq7uqa7z',
      },
    ],
    fee: [
      {
        amount: '0.0000001',
      },
    ],
  },
  requested: {
    xch: [],
    tokens: [],
    nfts: [
      {
        nftId: 'nft1uthmrkm6ycyqgknjlnpfk256qmth0ssrjeu6yn8rfvq3u702parqvfgnml',
      },
    ],
  },
};

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

export default function OfferBuilder(props: OfferBuilderProps): JSX.Element {
  const { onOfferCreated, readOnly = false } = props;
  const methods = useForm<OfferBuilderFormData>({
    defaultValues: mockedDefaultValue,
  });

  function handleSubmit(values: OfferBuilderFormData) {
    console.log('values', values);

    return;
    onOfferCreated(values);
  }

  return (
    <Form methods={methods} onSubmit={handleSubmit}>
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
