import React, { ReactNode } from 'react';
import styled from 'styled-components';
import { Box } from '@material-ui/core';
import Loading from '../Loading';

const StyledRoot = styled(Box)`
  position: relative;
  width: 100%;
`;

const StyledLoadingContainer = styled(Box)`
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  top: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background-color: rgba(0, 0, 0, 0.2);
`;

type Props = {
  children?: ReactNode;
  loading?: boolean;
  disabled?: boolean;
};

export default function LoadingOverlay(props: Props) {
  const { children, loading, disabled } = props;

  return (
    <StyledRoot>
      {children}
      {(loading || disabled) && (
        <StyledLoadingContainer>
          {!disabled && (
            <Loading center />
          )}
        </StyledLoadingContainer>
      )}
    </StyledRoot>
  );
}

LoadingOverlay.defaultProps = {
  children: undefined,
  loading: false,
  disabled: false,
};
