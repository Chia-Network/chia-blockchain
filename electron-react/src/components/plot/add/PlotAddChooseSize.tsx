import React from 'react';
import styled from 'styled-components';
import { Trans } from '@lingui/macro';
import { useFormContext } from 'react-hook-form';
import { CardStep, Select } from '@chia/core';
import { Grid, Link, FormControl, Typography, InputLabel, MenuItem, FormHelperText } from '@material-ui/core';
import { plotSizeOptions } from '../../../constants/plotSizes';
import StateColor from '../../../constants/StateColor';

const MIN_MAINNET_K_SIZE = 32;

const StyledFormHelperText = styled(FormHelperText)`
  color: ${StateColor.WARNING};
`;

export default function PlotAddChooseSize() {
  const { watch } = useFormContext();

  const plotSize = watch('plotSize');
  const isKLow = plotSize < MIN_MAINNET_K_SIZE;

  return (
    <CardStep
      step="1"
      title={(
        <Trans id="PlotAddChooseSize.title">Choose Plot Size</Trans>
      )}
    >
      <Typography variant="subtitle1">
        <Trans id="PlotAddChooseSize.description">
          {'Temporary files are created during the plotting process which exceeds the size of the final plot files. Make sure you have enough space. '}
          <Link target="_blank" href="https://github.com/Chia-Network/chia-blockchain/wiki/k-sizes">Learn more</Link>
        </Trans>
      </Typography>

      <Grid container>
        <Grid xs={12} sm={10} md={8} lg={6} item>
          <FormControl
            variant="filled"
            fullWidth
          >
            <InputLabel required focused>
              <Trans id="PlotAddChooseSize.plotSize">Plot Size</Trans>
            </InputLabel>
            <Select name="plotSize">
              {plotSizeOptions.map((option) => (
                <MenuItem value={option.value} key={option.value}>
                  {option.label}
                </MenuItem>
              ))}
            </Select>
            {isKLow && (
              <StyledFormHelperText>
                <Trans id="PlotAddChooseSize.kLow">
                  The minimum required size for mainnet is k=32
                </Trans>
              </StyledFormHelperText>
            )}
          </FormControl>
        </Grid>
      </Grid>
    </CardStep>
  );
}
