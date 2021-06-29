import React, { ReactNode, ReactElement } from 'react';
import styled from 'styled-components';
import { Flex, TooltipIcon } from '@chia/core';
import {
  Box,
  Card,
  CardContent,
  Typography,
  TypographyProps,
  CircularProgress,
} from '@material-ui/core';

const StyledCard = styled(Card)`
  height: 100%;
  overflow: visible;
  margin-bottom: -0.5rem;
`;

const StyledTitle = styled.div`
  margin-bottom: 0.5rem;
`;

const StyledValue = styled(Typography)`
  font-size: 1.25rem;
`;

type Props = {
  title: ReactNode;
  value: ReactNode;
  valueColor?: TypographyProps['color'];
  description?: ReactNode;
  loading?: boolean;
  tooltip?: ReactElement<any>;
};

export default function FarmCard(props: Props) {
  const { title, value, description, valueColor, loading, tooltip } = props;

  return (
    <StyledCard>
      <CardContent>
        <StyledTitle>
          <Flex gap={1} alignItems="center">
            <Typography color="textSecondary">
              {title}
            </Typography>
            {tooltip && <TooltipIcon>{tooltip}</TooltipIcon>}
          </Flex>
        </StyledTitle>
        {loading ? (
          <Box>
            <CircularProgress color="primary" size={25} />
          </Box>
        ) : (
          <StyledValue variant="h5" color={valueColor}>
            {value}
          </StyledValue>
        )}

        {description && (
          <Typography variant="caption" color="textSecondary">
            {description}
          </Typography>
        )}
      </CardContent>
    </StyledCard>
  );
}

FarmCard.defaultProps = {
  valueColor: 'primary',
  description: undefined,
  loading: false,
};
