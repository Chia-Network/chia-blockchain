import React, { ReactNode } from 'react';
import styled from 'styled-components';
import { Box } from '@material-ui/core';

const OuterWrapper = styled(({ ration, ...rest }) => <Box {...rest} />)`
  position: relative;
  width: 100%;
  height: 0;
  padding-bottom: ${(props) => (1 / props.ratio) * 100}%;
  overflow: hidden;
`;

export const InnerWrapper = styled(Box)`
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  left: 0;
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
