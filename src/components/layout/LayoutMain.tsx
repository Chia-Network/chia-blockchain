import React, { ReactElement, ReactNode } from 'react';
import { Box, Container } from '@material-ui/core';
import styled from 'styled-components';
import { Flex } from '@chia/core';
import DashboardTitle from '../dashboard/DashboardTitle';

const StyledContainer = styled(Container)`
  padding-top: ${({ theme }) => `${theme.spacing(3)}px`};
  padding-bottom: ${({ theme }) => `${theme.spacing(3)}px`};
`;

const StyledInnerContainer = styled(Box)`
  box-shadow: inset 6px 0 8px -8px rgba(0,0,0,0.2);
`;

type Props = {
  children?: ReactElement<any>;
  title?: ReactNode;
};

export default function LayoutMain(props: Props) {
  const { children, title } = props;

  return (
    <>
      <DashboardTitle>{title}</DashboardTitle>

      <StyledInnerContainer>
        {children && (
          <StyledContainer maxWidth="lg">
            <Flex flexDirection="column" gap={2}>
              {children}
            </Flex>
          </StyledContainer>
        )}
      </StyledInnerContainer>
    </>
  );
}

LayoutMain.defaultProps = {
  children: undefined,
};
