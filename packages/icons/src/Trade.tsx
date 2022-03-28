import React from 'react';
import { SvgIcon, SvgIconProps } from '@mui/material';
import TradeIcon from './images/trade.svg';

export default function Trade(props: SvgIconProps) {
  return <SvgIcon component={TradeIcon} viewBox="0 0 34 34" {...props} />;
}
