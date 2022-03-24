import React from 'react';
import { SvgIcon, SvgIconProps } from '@material-ui/core';
import TokensIcon from './images/Tokens.svg';

export default function Tokens(props: SvgIconProps) {
  return <SvgIcon component={TokensIcon} viewBox="0 0 48 48" {...props} />;
}
