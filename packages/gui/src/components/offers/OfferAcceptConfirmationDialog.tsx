import React from 'react';
import { Trans } from '@lingui/macro';
import { ConfirmDialog, CopyToClipboard, Flex } from '@chia/core';
import { Divider, Typography } from '@mui/material';
import styled from 'styled-components';

const StyledSummaryBox = styled.div`
  padding-left: ${({ theme }) => `${theme.spacing(2)}`};
  padding-right: ${({ theme }) => `${theme.spacing(2)}`};
`;

type OfferAcceptConfirmationDialogProps = {
  offeredUnknownCATs: string[];
};

export default function OfferAcceptConfirmationDialog(
  props: OfferAcceptConfirmationDialogProps,
): React.ReactElement {
  const { offeredUnknownCATs, ...rest } = props;

  return (
    <ConfirmDialog
      title={<Trans>Accept Offer</Trans>}
      confirmTitle={<Trans>Yes, Accept Offer</Trans>}
      confirmColor="primary"
      cancelTitle={<Trans>Cancel</Trans>}
      {...rest}
    >
      <Flex flexDirection="column" gap={3}>
        {offeredUnknownCATs.length > 0 && (
          <>
            <Flex flexDirection="column" gap={1}>
              <Typography variant="h6">
                <Trans>Warning</Trans>
              </Typography>
              <Typography variant="body1">
                <Trans>
                  One or more unknown tokens are being offered. Please verify
                  that the asset IDs of the tokens listed below match the asset
                  IDs of the tokens you expect to receive.
                </Trans>
              </Typography>
              <Typography variant="subtitle1">Unknown CATs:</Typography>
              <StyledSummaryBox>
                <Flex flexDirection="column">
                  {offeredUnknownCATs.map((assetId) => (
                    <Flex
                      alignItems="center"
                      justifyContent="space-between"
                      gap={1}
                    >
                      <Typography variant="caption">
                        {assetId.toLowerCase()}
                      </Typography>
                      <CopyToClipboard
                        value={assetId.toLowerCase()}
                        fontSize="small"
                      />
                    </Flex>
                  ))}
                </Flex>
              </StyledSummaryBox>
            </Flex>
            <Divider />
          </>
        )}
        <Typography>
          <Trans>
            Once you accept this offer, you will not be able to cancel the
            transaction. Are you sure you want to accept this offer?
          </Trans>
        </Typography>
      </Flex>
    </ConfirmDialog>
  );
}

OfferAcceptConfirmationDialog.defaultProps = {
  offeredUnknownCATs: [],
};
