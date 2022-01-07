import React, { ReactElement, ReactNode } from 'react';
import { Trans } from '@lingui/macro';
import { Container } from '@material-ui/core';
import styled from 'styled-components';
import { Flex, Loading } from '@chia/core';
import DashboardTitle from '../dashboard/DashboardTitle';
import { Shell } from 'electron';

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

const StyledBody = styled(Flex)`
  min-width: 0;
`;

const SendFeedback = styled.a`
  align-self: flex-end;
  padding-right: ${({ theme }) => `${theme.spacing(3)}px`};
  padding-bottom: ${({ theme }) => `${theme.spacing(3)}px`};
  color: rgb(128, 160, 194);
`;

type Props = {
  children?: ReactElement<any>;
  title?: ReactNode;
  loading?: boolean;
  loadingTitle?: ReactNode;
  bodyHeader?: ReactNode;
};

async function openSendFeedbackURL(): Promise<void> {
  try {
    const shell: Shell = (window as any).shell;
    await shell.openExternal('https://forms.gle/f19UKU52xtWGwQqH9');
  }
  catch (e) {
    console.error(e);
  }
}

export default function LayoutMain(props: Props) {
  const { children, title, loading, loadingTitle, bodyHeader } = props;

  return (
    <>
      <DashboardTitle>{title}</DashboardTitle>

      <StyledInnerContainer flexDirection="column">
        {bodyHeader}
        <StyledContainer maxWidth="lg">
          <StyledBody flexDirection="column" gap={2} flexGrow="1">
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
          </StyledBody>
        </StyledContainer>
      </StyledInnerContainer>
      <SendFeedback onClick={openSendFeedbackURL}>
        <Trans>Send Feedback</Trans>
      </SendFeedback>
    </>
  );
}

LayoutMain.defaultProps = {
  children: undefined,
  bodyHeader: undefined,
};
