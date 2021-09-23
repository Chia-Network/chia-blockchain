import React from 'react';
import { SvgIcon, SvgIconProps } from '@material-ui/core';
import PlotHeroIcon from './images/PlotHero.svg';

export default function PlotHero(props: SvgIconProps) {
  return <SvgIcon component={PlotHeroIcon} viewBox="0 0 67 54" {...props} />;
}
