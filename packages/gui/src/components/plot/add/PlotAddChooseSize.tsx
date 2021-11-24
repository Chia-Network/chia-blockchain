import React, { useEffect, useState } from 'react';
import styled from 'styled-components';
import { Trans } from '@lingui/macro';
import { useFormContext } from 'react-hook-form';
import { CardStep, ConfirmDialog, Link, Select, StateColor } from '@chia/core';
import {
  Grid,
  FormControl,
  Typography,
  InputLabel,
  MenuItem,
  FormHelperText,
} from '@material-ui/core';
import { plotSizeOptions } from '../../../constants/plotSizes';
import useOpenDialog from '../../../hooks/useOpenDialog';
import Plotter from '../../../types/Plotter';

const MIN_MAINNET_K_SIZE = 32;

const StyledFormHelperText = styled(FormHelperText)`
  color: ${StateColor.WARNING};
`;

type Props = {
  step: number;
  plotter: Plotter;
};

export default function PlotAddChooseSize(props: Props) {
  const { step, plotter } = props;
  const { watch, setValue } = useFormContext();
  const openDialog = useOpenDialog();

  const plotterName = watch('plotterName');
  const plotSize = watch('plotSize');
  const overrideK = watch('overrideK');
  const isKLow = plotSize < MIN_MAINNET_K_SIZE;

  const [allowedPlotSizes, setAllowedPlotSizes] = useState(plotSizeOptions.filter((option) => plotter.options.kSizes.includes(option.value)));

  useEffect(() => {
    setAllowedPlotSizes(plotSizeOptions.filter((option) => plotter.options.kSizes.includes(option.value)));
  }, [plotterName]);

  async function getConfirmation() {
    const canUse = await openDialog(
      <ConfirmDialog
        title={<Trans>The minimum required size for mainnet is k=32</Trans>}
        confirmTitle={<Trans>Yes</Trans>}
        confirmColor="danger"
      >
        <Trans>Are you sure you want to use k={plotSize}?</Trans>
      </ConfirmDialog>,
    );

    // @ts-ignore
    if (canUse) {
      setValue('overrideK', true);
    } else {
      setValue('plotSize', 32);
    }
  }

  useEffect(() => {
    if (plotSize === 25) {
      if (!overrideK) {
        getConfirmation();
      }
    } else {
      setValue('overrideK', false);
    }
  }, [plotSize, overrideK]); // eslint-disable-line

  return (
    <CardStep step={step} title={<Trans>Choose Plot Size</Trans>}>
      <Typography variant="subtitle1">
        <Trans>
          {
            'You do not need to be synced or connected to plot. Temporary files are created during the plotting process which exceed the size of the final plot files. Make sure you have enough space. '
          }
          <Link
            target="_blank"
            href="https://github.com/Chia-Network/chia-blockchain/wiki/k-sizes"
          >
            Learn more
          </Link>
        </Trans>
      </Typography>

      <Grid container>
        <Grid xs={12} sm={10} md={8} lg={6} item>
          <FormControl variant="filled" fullWidth>
            <InputLabel required focused>
              <Trans>Plot Size</Trans>
            </InputLabel>
            <Select name="plotSize">
              {allowedPlotSizes.map((option) => (
                <MenuItem value={option.value} key={option.value}>
                  {option.label}
                </MenuItem>
              ))}
            </Select>
            {isKLow && (
              <StyledFormHelperText>
                <Trans>The minimum required size for mainnet is k=32</Trans>
              </StyledFormHelperText>
            )}
          </FormControl>
        </Grid>
      </Grid>
    </CardStep>
  );
}
