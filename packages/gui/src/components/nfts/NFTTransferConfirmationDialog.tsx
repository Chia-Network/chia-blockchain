import React, { type ReactNode } from 'react';
import { Trans, Plural } from '@lingui/macro';
import styled from 'styled-components';
import {
  useCurrencyCode,
  chiaToMojo,
  ConfirmDialog,
  Flex,
  TooltipIcon,
  FormatLargeNumber,
} from '@chia/core';
import { Box, Divider, Typography } from '@mui/material';

const StyledTitle = styled(Box)`
  font-size: 0.625rem;
  color: rgba(255, 255, 255, 0.7);
`;

const StyledValue = styled(Box)`
  word-break: break-all;
`;

export type NFTTransferConfirmationDialogProps = {
  destination: string;
  fee: string;
  open?: boolean; // For use in openDialog()
  title?: ReactNode;
  description?: ReactNode;
  confirmTitle?: ReactNode;
  confirmColor?: string;
};

export default function NFTTransferConfirmationDialog(
  props: NFTTransferConfirmationDialogProps,
) {
  const {
    destination,
    fee,
    title = <Trans>Confirm NFT Transfer</Trans>,
    description = (
      <Trans>
        Once you initiate this transfer, you will not be able to cancel the
        transaction. Are you sure you want to transfer the NFT?
      </Trans>
    ),
    confirmTitle = <Trans>Transfer</Trans>,
    confirmColor = 'secondary',
    ...rest
  } = props;
  const feeInMojos = chiaToMojo(fee || 0);
  const currencyCode = useCurrencyCode();

  return (
    <ConfirmDialog
      title={title}
      confirmTitle={confirmTitle}
      confirmColor={confirmColor}
      cancelTitle={<Trans>Cancel</Trans>}
      {...rest}
    >
      <Flex flexDirection="column" gap={3}>
        <Typography variant="body1">{description}</Typography>
        <Divider />
        <Flex flexDirection="column" gap={1}>
          <Flex flexDirection="row" gap={1}>
            <Flex flexShrink={0}>
              <Typography variant="body1">
                <Trans>Destination:</Trans>
              </Typography>
            </Flex>
            <Flex
              flexDirection="row"
              alignItems="center"
              gap={1}
              sx={{ overflow: 'hidden' }}
            >
              <Typography noWrap variant="body1">
                {destination}
              </Typography>
              <TooltipIcon>
                <Flex flexDirection="column" gap={1}>
                  <StyledTitle>
                    <Trans>Destination</Trans>
                  </StyledTitle>
                  <StyledValue>
                    <Typography variant="caption">{destination}</Typography>
                  </StyledValue>
                </Flex>
              </TooltipIcon>
            </Flex>
          </Flex>
          <Flex flexDirection="row" gap={1}>
            <Typography variant="body1">Fee:</Typography>
            <Typography variant="body1">
              {fee || '0'} {currencyCode}
            </Typography>
            {feeInMojos > 0 && (
              <>
                <FormatLargeNumber value={feeInMojos} />
                <Box>
                  <Plural
                    value={feeInMojos.toNumber()}
                    one="mojo"
                    other="mojos"
                  />
                </Box>
              </>
            )}
          </Flex>
        </Flex>
      </Flex>
    </ConfirmDialog>
  );
}
