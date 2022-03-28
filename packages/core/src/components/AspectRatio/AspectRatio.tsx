import React, { ReactNode } from 'react';
import styled from 'styled-components';
import { Box } from '@mui/material';

const OuterWrapper = styled(({ ration, ...rest }) => <Box {...rest} />)`
  position: relative;
  width: 100%;
  display: flex;

  &:before {
    padding-bottom: ${(props) => (1 / props.ratio) * 100}%;
    content: '';
    float: left;
  }

  &:after {
    display: table;
    content: '';
    clear: both;
  }
`;

export const InnerWrapper = styled(Box)`
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-content: center;
  align-self: stretch;
  width: 100%;
`;

type Props = {
  ratio: number;
  children: ReactNode;
};

export default function AspectRatio(props: Props) {
  const { children, ratio } = props;

  return (
    <OuterWrapper ratio={ratio}>
      <InnerWrapper>
        {children}
      </InnerWrapper>
    </OuterWrapper>
  );
}
