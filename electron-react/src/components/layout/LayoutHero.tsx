import React, { ReactNode } from 'react';
import { Box } from '@material-ui/core';
import styled from 'styled-components';

const StyledWrapper = styled(Box)`
  height: 100%;
  background: linear-gradient(45deg, #222222 30%, #333333 90%);
`;

type Props = {
  children: ReactNode,
};

export default function LayoutHero(props: Props) {
  const { children } = props;

  return (
    <StyledWrapper
      display="flex"
      flexDirection="column"
      justifyContent="center"
      alignItems="center"
    >
      {children}
    </StyledWrapper>
  );
}
