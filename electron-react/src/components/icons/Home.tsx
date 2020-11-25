import React from 'react';
import { SvgIcon, SvgIconProps } from '@material-ui/core';
import styled from 'styled-components';
import { ReactComponent as HomeIcon } from './images/home.svg';

const StyledHomeIcon = styled(HomeIcon)`
  path {
    stroke: ${({ theme }) =>
      theme.palette.type === 'dark' ? 'white' : '#757575'};
    stroke-width: 1;
  }
`;

export default function Home(props: SvgIconProps) {
  return <SvgIcon component={StyledHomeIcon} viewBox="0 0 32 31" {...props} />;
}
