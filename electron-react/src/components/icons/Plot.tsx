import React from 'react';
import { SvgIcon, SvgIconProps } from '@material-ui/core';
import { ReactComponent as PlotIcon } from './images/plot.svg';

export default function Plot(props: SvgIconProps) {
  return <SvgIcon component={PlotIcon} viewBox="0 0 40 32" {...props} />;
}
