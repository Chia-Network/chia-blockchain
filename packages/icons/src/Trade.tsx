import React from 'react';
import { SvgIcon, SvgIconProps } from '@material-ui/core';
import TradeIcon from './images/trade.svg';

export default function Trade(props: SvgIconProps) {
  return <SvgIcon component={TradeIcon} viewBox="0 0 34 34" {...props} />;
}
