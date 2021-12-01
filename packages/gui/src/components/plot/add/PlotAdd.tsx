import React, { useState, useEffect, useRef } from 'react';
import { useNavigate, useLocation } from 'react-router';
import { t, Trans } from '@lingui/macro';
import { useGetFingerprintQuery, useGetPlottersQuery, useStartPlottingMutation, useCreateNewPoolWalletMutation } from '@chia/api-react';
import { ChevronRight as ChevronRightIcon } from '@material-ui/icons';
import { useForm, SubmitHandler } from 'react-hook-form';
import { useCurrencyCode, useShowError, ButtonLoading, Flex, Form, FormBackButton, Loading, Suspender } from '@chia/core';
import { PlotHeaderSource } from '../PlotHeader';
import PlotAddChoosePlotter from './PlotAddChoosePlotter';
import PlotAddChooseSize from './PlotAddChooseSize';
import PlotAddNumberOfPlots from './PlotAddNumberOfPlots';
import PlotAddSelectTemporaryDirectory from './PlotAddSelectTemporaryDirectory';
import PlotAddSelectFinalDirectory from './PlotAddSelectFinalDirectory';
import PlotAddNFT from './PlotAddNFT';
import PlotAddConfig from '../../../types/PlotAdd';
import plotSizes from '../../../constants/plotSizes';
import PlotNFTState from '../../../constants/PlotNFTState';
import PlotterName from '../../../constants/PlotterName';
import { defaultPlotter } from '../../../modules/plotterConfiguration';
import toBech32m from '../../../util/toBech32m';
import useUnconfirmedPlotNFTs from '../../../hooks/useUnconfirmedPlotNFTs';

type FormData = PlotAddConfig & {
  p2_singleton_puzzle_hash?: string;
  createNFT?: boolean;
};

export default function PlotAdd() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState<boolean>(false);
  const currencyCode = useCurrencyCode();
  const showError = useShowError();

  const { data: fingerprint, isLoadingFingerprint } = useGetFingerprintQuery();
  const { data: plotters, isLoadingPlotters } = useGetPlottersQuery();
  const [startPlotting] = useStartPlottingMutation();
  const [createNewPoolWallet] = useCreateNewPoolWalletMutation();
  const addNFTref = useRef();
  const { state } = useLocation();
  const unconfirmedNFTs = useUnconfirmedPlotNFTs();

  const otherDefaults = {
    plotCount: 1,
    queue: 'default',
    finalLocation: '',
    workspaceLocation: '',
    workspaceLocation2: '',
    farmerPublicKey: '',
    poolPublicKey: '',
    excludeFinalDir: false,
    p2_singleton_puzzle_hash: state?.p2_singleton_puzzle_hash ?? '',
    createNFT: false,
  };

  const isLoading = isLoadingFingerprint || isLoadingPlotters || !currencyCode;

  const defaultsForPlotter = (plotterName: PlotterName) => {
    const plotterDefaults = plotters[plotterName]?.defaults ?? defaultPlotter().defaults;
    const plotSize = plotterDefaults.plotSize;
    const maxRam = plotSizes.find((element) => element.value === plotSize)?.defaultRam;
    const defaults = {
      ...plotterDefaults,
      ...otherDefaults,
      maxRam: maxRam,
    };

    return defaults;
  }

  const methods = useForm<FormData>({
    shouldUnregister: false,
    defaultValues: isLoading ? {} : defaultsForPlotter(PlotterName.CHIAPOS),
  });

  const { watch, setValue, reset } = methods;
  const plotterName = watch('plotterName') as PlotterName;
  const plotSize = watch('plotSize');

  useEffect(() => {
    const plotSizeConfig = plotSizes.find((item) => item.value === plotSize);
    if (plotSizeConfig) {
      setValue('maxRam', plotSizeConfig.defaultRam);
    }
  }, [plotSize, setValue]);

  if (isLoading) {
    return <Suspender />;
  }


  let plotter = plotters[plotterName] ?? defaultPlotter();
  let step: number = 1;
  const allowTempDirectorySelection: boolean = plotter.options.haveBladebitOutputDir === false;



  const handlePlotterChanged = (newPlotterName: PlotterName) => {
    const defaults = defaultsForPlotter(newPlotterName);
    reset(defaults);
  };

  const handleSubmit: SubmitHandler<FormData> = async (data) => {
    try {
      setLoading(true);
      const { p2_singleton_puzzle_hash, delay, createNFT, ...rest } = data;
      const { farmerPublicKey, poolPublicKey } = rest;

      let selectedP2SingletonPuzzleHash = p2_singleton_puzzle_hash;

      if (!currencyCode) {
        throw new Error(t`Currency code is not defined`);
      }

      if (createNFT) {
        // create nft
        const nftData = await addNFTref.current?.getSubmitData();

        const {
          fee,
          initialTargetState,
          initialTargetState: { state },
        } = nftData;
        const { transaction, p2SingletonPuzzleHash } = await createNewPoolWallet(initialTargetState, fee).unwrap();

        if (!p2SingletonPuzzleHash) {
          throw new Error(t`p2SingletonPuzzleHash is not defined`);
        }

        unconfirmedNFTs.add({
          transactionId: transaction.name,
          state:
            state === 'SELF_POOLING'
              ? PlotNFTState.SELF_POOLING
              : PlotNFTState.FARMING_TO_POOL,
          poolUrl: initialTargetState.pool_url,
        });

        selectedP2SingletonPuzzleHash = p2SingletonPuzzleHash;
      }

      const plotAddConfig = {
        ...rest,
        delay: delay * 60,
      };

      if (selectedP2SingletonPuzzleHash) {
        plotAddConfig.c = toBech32m(
          selectedP2SingletonPuzzleHash,
          currencyCode.toLowerCase(),
        );
      }

      if (
        !selectedP2SingletonPuzzleHash &&
        !farmerPublicKey &&
        !poolPublicKey &&
        fingerprint
      ) {
        plotAddConfig.fingerprint = fingerprint;
      }

      await startPlotting(plotAddConfig).unwrap();

      navigate('/dashboard/plot');
    } catch (error) {
      await showError(error);
    } finally {
      setLoading(false);
    }
  };

  if (isLoading) {
    return <Suspender />;
  }

  return (
    <Form methods={methods} onSubmit={handleSubmit}>
      <PlotHeaderSource>
        <Flex alignItems="center">
          <ChevronRightIcon color="secondary" />
          <Trans>Add a Plot</Trans>
        </Flex>
      </PlotHeaderSource>
      <Flex flexDirection="column" gap={3}>
        <PlotAddChoosePlotter step={step++} onChange={handlePlotterChanged} />
        <PlotAddChooseSize step={step++} plotter={plotter} />
        <PlotAddNumberOfPlots step={step++} plotter={plotter} />
        {allowTempDirectorySelection && (
          <PlotAddSelectTemporaryDirectory step={step++} plotter={plotter} />
        )}
        <PlotAddSelectFinalDirectory step={step++} plotter={plotter} />
        <PlotAddNFT ref={addNFTref} step={step++} plotter={plotter} />
        <Flex gap={1}>
          <FormBackButton variant="outlined" />
          <ButtonLoading
            loading={loading}
            color="primary"
            type="submit"
            variant="contained"
          >
            <Trans>Create</Trans>
          </ButtonLoading>
        </Flex>
      </Flex>
    </Form>
  );
}
