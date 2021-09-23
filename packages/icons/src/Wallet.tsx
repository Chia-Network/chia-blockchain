import React from 'react';
import { SvgIcon, SvgIconProps } from '@material-ui/core';
import WalletIcon from './images/wallet.svg';

export default function Wallet(props: SvgIconProps) {
  return <SvgIcon component={WalletIcon} viewBox="0 0 32 39" {...props} />;
}
