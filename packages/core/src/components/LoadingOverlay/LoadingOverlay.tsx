import React, { ReactNode } from 'react';
import styled from 'styled-components';
import Loading from '../Loading';

const StyledRoot = styled.div`
  position: relative;
  width: 100%;
`;

const StyledLoadingContainer = styled.div`
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
  loading: boolean;
};

export default function LoadingOverlay(props: Props) {
  const { children, loading } = props;

  return (
    <StyledRoot>
      {children}
      {loading && (
        <StyledLoadingContainer>
          <Loading center />
        </StyledLoadingContainer>
      )}
    </StyledRoot>
  );
}
