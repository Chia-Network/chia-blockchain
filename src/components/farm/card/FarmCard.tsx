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
        <Flex gap={1} alignItems="center">
          <Typography color="textSecondary" gutterBottom>
            {title}
          </Typography>
          {tooltip && <TooltipIcon>{tooltip}</TooltipIcon>}
        </Flex>
        {loading ? (
          <Box>
            <CircularProgress color="primary" size={25} />
          </Box>
        ) : (
          <Typography variant="h5" color={valueColor}>
            {value}
          </Typography>
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
