import React from 'react';
import { SvgIcon, SvgIconProps } from '@mui/material';
import PlotIcon from './images/plot.svg';

export default function Plot(props: SvgIconProps) {
  return <SvgIcon component={PlotIcon} viewBox="0 0 40 32" {...props} />;
}
