import React, { useMemo, useRef, useState } from 'react';
import { Trans } from '@lingui/macro';
import { useGetWalletsQuery } from '@chia/api-react';
import { Flex, ButtonLoading, Loading } from '@chia/core';
import { Grid } from '@mui/material';
import { useNavigate } from 'react-router-dom';
import type OfferSummary from '../../@types/OfferSummary';
import offerToOfferBuilderData from '../../util/offerToOfferBuilderData';
import OfferBuilder from './OfferBuilder';
import OfferNavigationHeader from './OfferNavigationHeader';
import type OfferBuilderData from '../../@types/OfferBuilderData';
import useAcceptOfferHook from '../../hooks/useAcceptOfferHook';

export type OfferBuilderViewerProps = {
  offerData: string;
  offerSummary: OfferSummary;
  referrerPath?: string;
};

export default function OfferBuilderViewer(props: OfferBuilderViewerProps) {
  const { offerSummary, referrerPath, offerData } = props;

  const navigate = useNavigate();
  const [acceptOffer] = useAcceptOfferHook();
  const [isAccepting, setIsAccepting] = useState<boolean>(false);
  const { data: wallets, isLoading: isLoadingWallets } = useGetWalletsQuery();
  const offerBuilderRef = useRef<{ submit: () => void } | undefined>(undefined);

  const canAccept = !!offerData;

  const offerBuilderData = useMemo(() => {
    if (!offerSummary || !wallets) {
      return undefined;
    }

    return offerToOfferBuilderData(offerSummary, wallets);
  }, [offerSummary, wallets]);

  const isLoading = isLoadingWallets || !offerBuilderData;

  async function handleSubmit(values: OfferBuilderData) {
    const {
      offered: { fee },
    } = values;

    if (isAccepting || !canAccept) {
      return;
    }

    const feeAmount = fee?.[0]?.amount ?? '0'; // TODO convert to mojo here insted of in hook

    await acceptOffer(
      offerData,
      offerSummary,
      feeAmount,
      (accepting: boolean) => setIsAccepting(accepting),
      () => navigate('/dashboard/offers'),
    );
  }

  function handleAcceptOffer() {
    offerBuilderRef.current?.submit();
  }

  return (
    <Grid container>
      <Flex flexDirection="column" flexGrow={1} gap={4}>
        <Flex alignItems="center" justifyContent="space-between" gap={2}>
          <OfferNavigationHeader referrerPath={referrerPath} />
          {canAccept && (
            <ButtonLoading
              variant="contained"
              color="primary"
              onClick={handleAcceptOffer}
              isLoading={isAccepting}
              disableElevation
            >
              <Trans>Accept Offer</Trans>
            </ButtonLoading>
          )}
        </Flex>
        {isLoading ? (
          <Loading />
        ) : (
          <OfferBuilder
            defaultValues={offerBuilderData}
            onSubmit={handleSubmit}
            ref={offerBuilderRef}
            readOnly
            viewer
          />
        )}
      </Flex>
    </Grid>
  );
}
