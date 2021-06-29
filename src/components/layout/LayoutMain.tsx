import React, { ReactElement, ReactNode } from 'react';
import { Box, Container } from '@material-ui/core';
import styled from 'styled-components';
import { Flex, Loading } from '@chia/core';
import DashboardTitle from '../dashboard/DashboardTitle';

const StyledContainer = styled(Container)`
  padding-top: ${({ theme }) => `${theme.spacing(3)}px`};
  padding-bottom: ${({ theme }) => `${theme.spacing(3)}px`};
  flex-grow: 1;
  display: flex;
`;

const StyledInnerContainer = styled(Flex)`
  box-shadow: inset 6px 0 8px -8px rgba(0, 0, 0, 0.2);
  flex-grow: 1;
`;

type Props = {
  children?: ReactElement<any>;
  title?: ReactNode;
  loading?: boolean;
  loadingTitle?: ReactNode;
};

export default function LayoutMain(props: Props) {
  const { children, title, loading, loadingTitle } = props;

  return (
    <>
      <DashboardTitle>{title}</DashboardTitle>

      <StyledInnerContainer>
        <StyledContainer maxWidth="lg">
          <Flex flexDirection="column" gap={2} flexGrow="1">
            {loading ? (
              <Flex
                flexDirection="column"
                flexGrow={1}
                alignItems="center"
                justifyContent="center"
              >
                <Loading>{loadingTitle}</Loading>
              </Flex>
            ) : (
              children
            )}
          </Flex>
        </StyledContainer>
      </StyledInnerContainer>
    </>
  );
}

LayoutMain.defaultProps = {
  children: undefined,
};
