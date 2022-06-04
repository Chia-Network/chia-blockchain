import { Typography } from '@mui/material';
import { Trans } from '@lingui/macro';
import React, { Component, type ReactNode } from 'react';
import StackTrace from "stacktrace-js";
import { styled } from '@mui/styles';
import qs from 'qs';
import LayoutHero from '../LayoutHero';
import Button from '../Button';
import Link from '../Link';
import Flex from '../Flex';

const StyledPre = styled(Typography)(() => ({
  whiteSpace: 'pre-wrap',
}));

function formatStackTrace(stack: []) {
  const stackTrace = stack.map(({ fileName, columnNumber, lineNumber, functionName }) => {
    return `at ${fileName}:${lineNumber}:${columnNumber} ${functionName}`;
  });
  return stackTrace.join('\n');
}

type ErrorBoundaryProps = {
  children?: ReactNode;
};

export default class ErrorBoundary extends Component {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = {
      hasError: false,
      error: null,
      stacktrace: '',
    };
  }

  static getDerivedStateFromError(error) {
    // Update state so the next render will show the fallback UI.
    return {
      hasError: true,
      error,
    };
  }

  async componentDidUpdate(_prevProps, prevState) {
    if (this.state.error && prevState.error !== this.state.error) {
      this.setState({
        stacktrace: formatStackTrace(await StackTrace.fromError(this.state.error)),
      });
    }
  }

  handleReload = () => {
    window.location.hash = '#/';
    window.location.reload();
  }

  render() {
    if (this.state.hasError) {
      const { stacktrace, error } = this.state;
      const issueLink = `https://github.com/Chia-Network/chia-blockchain-gui/issues/new?${qs.stringify({
        labels: 'bug',
        template: 'bug_report.yaml',
        title: `[BUG] ${error.message}`,
        ui: 'GUI',
        logs: `${error.message}\n\nURL\n${window.location.hash}\n\nStacktrace\n${stacktrace}`,
      })}`
      // You can render any custom fallback UI
      return (
        <LayoutHero>
          <Flex flexDirection="column" gap={4}>
            <Typography variant="h5" textAlign="center" color="danger">
              <Trans>Something went wrong</Trans>
            </Typography>

            <Flex flexDirection="column">
              <Typography variant="h6" >
                <Trans>Error:</Trans> {error.message}
              </Typography>
              <StyledPre variant="body2">
                {stacktrace}
              </StyledPre>
            </Flex>

            <Flex justifyContent="center">
              <Link target="_blank" href={issueLink}>
                <Button><Trans>Report an Issue</Trans></Button>
              </Link>
              &nbsp;
              <Button onClick={this.handleReload} color="primary">
                <Trans>Reload Application</Trans>
              </Button>
            </Flex>
          </Flex>
        </LayoutHero>
      );
    }

    return this.props.children;
  }
}
