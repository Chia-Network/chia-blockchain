import React, { useMemo } from 'react';
import { useWatch } from 'react-hook-form';
import { t, Trans } from '@lingui/macro';
import { CardStep, Select, StateColor } from '@chia/core';
import { useGetPlottersQuery } from '@chia/api-react';
import {
  FormControl,
  FormHelperText,
  Grid,
  InputLabel,
  MenuItem,
  Typography,
} from '@mui/material';
import styled from 'styled-components';
import { defaultPlotter, PlotterName } from '@chia/api';
import type { Plotter, PlotterMap } from '@chia/api';

type Props = {
  step: number;
  onChange: (plotter: PlotterName) => void;
};

const StyledFormHelperText = styled(FormHelperText)`
  color: ${StateColor.WARNING};
`;

export default function PlotAddChoosePlotter(props: Props) {
  const { step, onChange } = props;
  const plotterName: PlotterName | undefined = useWatch<PlotterName>({name: 'plotterName'});
  const { data: plotters } = useGetPlottersQuery();

  function displayablePlotters(plotters: PlotterMap<PlotterName, Plotter>): PlotterName[] {
    const displayablePlotters = Object.keys(plotters) as PlotterName[];
    // Sort chiapos to the top of the list
    displayablePlotters.sort((a, b) => a == PlotterName.CHIAPOS ? -1 : a.localeCompare(b));
    return displayablePlotters;
  }

  const displayedPlotters = useMemo(() => {
    return plotters ? displayablePlotters(plotters) : [];
  }, [plotters]);


  const handleChange = async (event: any) => {
    const selectedPlotterName: PlotterName = event.target.value as PlotterName;
    onChange(selectedPlotterName);
  };

  const isPlotterInstalled = (plotterName: PlotterName): boolean => {
    const installed = plotters[plotterName]?.installInfo?.installed ?? false;
    return installed;
  }

  const isPlotterSupported = (plotterName: PlotterName): boolean => {
    const installed = plotters[plotterName]?.installInfo?.installed ?? false;
    const supported = installed || (plotters[plotterName]?.installInfo?.canInstall ?? false);
    return supported;
  }

  function plotterDisplayName(plotterName: PlotterName): string {
    const plotter = plotters[plotterName] ?? defaultPlotter;
    const { version } = plotter;
    const installed = plotter.installInfo?.installed ?? false;
    let displayName = plotter.displayName;

    if (version) {
      displayName += " " + version;
    }

    if (!isPlotterSupported(plotterName)) {
      displayName += " " + t`(Not Supported)`;
    }
    else if (!installed) {
      displayName += " " + t`(Not Installed)`;
    }

    return displayName;
  }

  const plotterWarningString = (plotterName: PlotterName | undefined): string | undefined => {
    if (plotterName === PlotterName.BLADEBIT) {
      return plotters[PlotterName.BLADEBIT]?.installInfo?.bladebitMemoryWarning;
    }
    return undefined;
  };

  const warning = plotterWarningString(plotterName);

  return (
    <CardStep step={step} title={<Trans>Choose Plotter</Trans>}>
      <Typography variant="subtitle1">
        <Trans>
            Depending on your system configuration, you may find that an alternative plotter
            produces plots faster than the default Chia Proof of Space plotter. If unsure,
            use the default Chia Proof of Space plotter.
        </Trans>
      </Typography>

      <Grid container>
        <Grid xs={12} sm={10} md={8} lg={6} item>
          <FormControl variant="filled" fullWidth>
            <InputLabel required focused>
              <Trans>Plotter</Trans>
            </InputLabel>
            <Select
              name="plotterName"
              onChange={handleChange}
              value={plotterName}
            >
              { displayedPlotters.map((plotter) => (
                <MenuItem value={plotter} key={plotter} disabled={!isPlotterInstalled(plotter) || !isPlotterSupported(plotter)}>
                  {plotterDisplayName(plotter)}
                </MenuItem>
              ))}
            </Select>
            {warning && (
              <StyledFormHelperText>
                <Trans>{warning}</Trans>
              </StyledFormHelperText>
            )}
          </FormControl>
        </Grid>
      </Grid>
    </CardStep>
  )
}
