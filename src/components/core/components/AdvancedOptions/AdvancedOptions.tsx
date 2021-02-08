import React, { useState, ReactNode } from 'react';
import { Trans } from '@lingui/macro';
import { Typography } from '@material-ui/core';
import styled from 'styled-components';
import {
  KeyboardArrowUp as KeyboardArrowUpIcon,
  KeyboardArrowDown as KeyboardArrowDownIcon,
} from '@material-ui/icons';
import Flex from '../Flex';
import Accordion from '../Accordion';

const StyledToggleAdvancedOptions = styled(({ expanded, ...rest }) => (
  <Typography {...rest} />
))`
  cursor: pointer;
`;

type Props = {
  children?: ReactNode,
  expanded: boolean,
};

export default function AdvancedOptions(props: Props) {
  const { children, expanded: defaultExpanded } = props;
  const [isExpanded, setIsExpanded] = useState<boolean>(defaultExpanded);

  function handleToggle() {
    setIsExpanded(!isExpanded);
  }

  return (
    <Flex flexDirection="column" gap={1}>
      <StyledToggleAdvancedOptions
        variant="caption"
        expanded={isExpanded}
        onClick={handleToggle}
      >
        {isExpanded ? (
          <Flex alignItems="center">
            <KeyboardArrowUpIcon />
            <Trans>
              Hide Advanced Options
            </Trans>
          </Flex>
        ) : (
          <Flex alignItems="center">
            <KeyboardArrowDownIcon />
            <Trans>
              Show Advanced Options
            </Trans>
          </Flex>
        )}
      </StyledToggleAdvancedOptions>

      <Accordion expanded={isExpanded}>
        {children}
      </Accordion>
    </Flex>
  )
}

AdvancedOptions.defaultProps = {
  expanded: false,
  children: undefined,
};
