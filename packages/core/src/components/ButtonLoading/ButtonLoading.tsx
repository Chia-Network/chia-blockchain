import React from 'react';
import styled from 'styled-components';
import { Box, CircularProgress } from '@material-ui/core';
import Button, { ButtonProps } from '../Button';

const StyledWrapper = styled(Box)`
  position: relative;
  display: ${({ fullWidth }) => fullWidth ?'block' : 'inline-block'};
`;

const StyledLoading = styled(CircularProgress)`
  position: absolute;
  top: 50%;
  left: 50%;
  margin-top: -12px;
  margin-left: -12px;
`;

const StyledButtonContent = styled.span`
  visibility: ${({ hide }) => (hide ? 'hidden' : 'visible')};
`;

type Props = ButtonProps & {
  loading?: boolean;
  mode?: 'autodisable' | 'hidecontent';
};

export default function ButtonLoading(props: Props) {
  const { loading, onClick, mode, children, disabled, ...rest } = props;

  function handleClick(...args: any[]) {
    if (!loading && onClick) {
      onClick(...args);
    }
  }

  const disabledButton = mode === 'autodisable' && loading ? true : disabled;

  return (
    <StyledWrapper {...rest}>
      <Button onClick={handleClick} {...rest} disabled={disabledButton}>
        <StyledButtonContent hide={mode === 'hidecontent' && loading}>
          {children}
        </StyledButtonContent>
      </Button>
      {loading && <StyledLoading size={24} />}
    </StyledWrapper>
  );
}

ButtonLoading.defaultProps = {
  loading: false,
  mode: 'autodisable',
};
