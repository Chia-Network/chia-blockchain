import React from 'react';
import { SvgIcon, SvgIconProps } from '@mui/material';
import styled from 'styled-components';
import HomeIcon from './images/home.svg';

function getColor({ theme, color }) {
  if (color !== 'inherit') {
    return color;
  }
  return theme.palette.type === 'dark' ? 'white' : '#757575';
}

const StyledHomeIcon = styled(HomeIcon)`
  path {
    stroke: ${getColor};
    stroke-width: 2;
  }
`;

export default function Home(props: SvgIconProps) {
  return <SvgIcon component={StyledHomeIcon} viewBox="0 0 32 31" {...props} />;
}
