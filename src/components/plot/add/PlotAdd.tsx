import React, { useEffect } from 'react';
import { useHistory, useLocation } from 'react-router';
import { useDispatch, useSelector } from 'react-redux';
import { Trans } from '@lingui/macro';
import { Button } from '@material-ui/core';
import { ChevronRight as ChevronRightIcon } from '@material-ui/icons';
import { useForm, SubmitHandler } from 'react-hook-form';
import { Flex, Form, FormBackButton, Loading } from '@chia/core';
import { PlotHeaderSource } from '../PlotHeader';
import PlotAddChooseSize from './PlotAddChooseSize';
import PlotAddNumberOfPlots from './PlotAddNumberOfPlots';
import PlotAddSelectTemporaryDirectory from './PlotAddSelectTemporaryDirectory';
import PlotAddSelectFinalDirectory from './PlotAddSelectFinalDirectory';
import PlotAddNFT from './PlotAddNFT';
import { plotQueueAdd } from '../../../modules/plotQueue';
import PlotAddConfig from '../../../types/PlotAdd';
import plotSizes, { defaultPlotSize } from '../../../constants/plotSizes';
import useCurrencyCode from '../../../hooks/useCurrencyCode';
import type { RootState } from '../../../modules/rootReducer';
import toBech32m from '../../../util/toBech32m';

type FormData = PlotAddConfig & {
  p2_singleton_puzzle_hash?: string;
};

export default function PlotAdd() {
  const history = useHistory();
  const { state } = useLocation();
  const dispatch = useDispatch();
  const currencyCode = useCurrencyCode();
  const fingerprint = useSelector((state: RootState) => state.wallet_state.selected_fingerprint);

  console.log('state', state);

  const methods = useForm<FormData>({
    shouldUnregister: false,
    defaultValues: {
      plotSize: defaultPlotSize.value,
      plotCount: 1,
      maxRam: defaultPlotSize.defaultRam,
      numThreads: 2,
      numBuckets: 128,
      queue: "default",
      finalLocation: '',
      workspaceLocation: '',
      workspaceLocation2: '',
      farmerPublicKey: '',
      poolPublicKey: '',
      delay: 0,
      parallel: false,
      disableBitfieldPlotting: false,
      excludeFinalDir: false,
      p2_singleton_puzzle_hash: state?.p2_singleton_puzzle_hash ?? '',
    },
  });

  const { watch, setValue } = methods;
  const plotSize = watch('plotSize');

  useEffect(() => {
    const plotSizeConfig = plotSizes.find(item => item.value === plotSize);
    if (plotSizeConfig) {
      setValue('maxRam', plotSizeConfig.defaultRam);
    }
  }, [plotSize, setValue]);

  const handleSubmit: SubmitHandler<FormData> = async (data) => {
    const { p2_singleton_puzzle_hash, delay, ...rest } = data;
    const { farmerPublicKey, poolPublicKey } = rest;

    if (!currencyCode) {
      throw new Error('Currency code is not defined');
    }

    const plotAddConfig = {
      ...rest,
      delay: delay * 60,
    };

    if (p2_singleton_puzzle_hash) {
      plotAddConfig.c = toBech32m(p2_singleton_puzzle_hash, currencyCode.toLowerCase());
    }

    if (!p2_singleton_puzzle_hash && !farmerPublicKey && !poolPublicKey && fingerprint) {
      plotAddConfig.fingerprint = fingerprint;
    }

    console.log('plotAddConfig', plotAddConfig);

    await dispatch(plotQueueAdd(plotAddConfig));

    history.push('/dashboard/plot');
  }

  if (!currencyCode) {
    return (
      <Flex alignItems="center">
        <Loading />
      </Flex>
    );
  }

  return (
    <Form
      methods={methods}
      onSubmit={handleSubmit}>
      <PlotHeaderSource>
        <Flex alignItems="center">
          <ChevronRightIcon color="secondary" />
          <Trans>
            Add a Plot
          </Trans>
        </Flex>
      </PlotHeaderSource>
      <Flex flexDirection="column" gap={3}>
        <PlotAddChooseSize />
        <PlotAddNumberOfPlots />
        <PlotAddSelectTemporaryDirectory />
        <PlotAddSelectFinalDirectory />
        <PlotAddNFT />
        <Flex gap={1}>
          <FormBackButton variant="contained" />
          <Button color="primary" type="submit" variant="contained">
            <Trans>
              Create Plot
            </Trans>
          </Button>
        </Flex>
      </Flex>
    </Form>
  );
}
