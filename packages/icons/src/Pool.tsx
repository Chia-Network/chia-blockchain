import React from 'react';
import { SvgIcon, SvgIconProps } from '@material-ui/core';
import FarmIcon from './images/pool.svg';

export default function Farm(props: SvgIconProps) {
  return <SvgIcon component={FarmIcon} viewBox="0 0 34 34" {...props} />;
}
