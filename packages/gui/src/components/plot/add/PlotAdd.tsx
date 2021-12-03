import React from 'react';
import { useGetLoggedInFingerprintQuery, useGetPlottersQuery } from '@chia/api-react';
import { useCurrencyCode, Suspender } from '@chia/core';
import PlotAddConfig from '../../../types/PlotAdd';
import useUnconfirmedPlotNFTs from '../../../hooks/useUnconfirmedPlotNFTs';
import PlotAddForm from './PlotAddForm';

type FormData = PlotAddConfig & {
  p2SingletonPuzzleHash?: string;
  createNFT?: boolean;
};

export default function PlotAdd() {
  const currencyCode = useCurrencyCode();
  const { isLoading: isLoadingUnconfirmedPlotNFTs, add: addUnconfirmedPlotNFT } = useUnconfirmedPlotNFTs();
  const { data: fingerprint, isLoading: isLoadingFingerprint } = useGetLoggedInFingerprintQuery();
  const { data: plotters, isLoading: isLoadingPlotters } = useGetPlottersQuery();

  const isLoading = isLoadingFingerprint || isLoadingPlotters || !currencyCode || isLoadingUnconfirmedPlotNFTs;

  if (isLoading) {
    return (
      <Suspender />
    );
  }
  
  return (
    <PlotAddForm
      currencyCode={currencyCode}
      fingerprint={fingerprint}
      plotters={plotters}
    />
  );
}
