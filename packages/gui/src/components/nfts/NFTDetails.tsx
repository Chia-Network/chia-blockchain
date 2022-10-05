import React, { useMemo } from 'react';
import { Trans } from '@lingui/macro';
import {
  Flex,
  CardKeyValue,
  CopyToClipboard,
  Tooltip,
  Truncate,
  truncateValue,
  Link,
} from '@chia/core';
import { Box, Typography } from '@mui/material';
import { stripHexPrefix } from '../../util/utils';
import { didToDIDId } from '../../util/dids';
import { convertRoyaltyToPercentage } from '../../util/nfts';
import useNFTMinterDID from '../../hooks/useNFTMinterDID';
import styled from 'styled-components';

/* ========================================================================== */

const StyledTitle = styled(Box)`
  font-size: 0.625rem;
  color: rgba(255, 255, 255, 0.7);
`;

const StyledValue = styled(Box)`
  word-break: break-all;
`;

/* ========================================================================== */

export default function NFTDetails(props: NFTDetailsProps) {
  const { nft, metadata } = props;
  const {
    didId: minterDID,
    hexDIDId: minterHexDIDId,
    didName: minterDIDName,
    isLoading: isLoadingMinterDID,
  } = useNFTMinterDID(nft.$nftId);

  const details = useMemo(() => {
    if (!nft) {
      return [];
    }

    const { dataUris = [] } = nft;

    const rows = [
      {
        key: 'nftId',
        label: <Trans>NFT ID</Trans>,
        value: (
          <Truncate ValueProps={{ variant: 'body2' }} tooltip copyToClipboard>
            {nft.$nftId}
          </Truncate>
        ),
      },
      {
        key: 'id',
        label: <Trans>Launcher ID</Trans>,
        value: (
          <Truncate ValueProps={{ variant: 'body2' }} tooltip copyToClipboard>
            {stripHexPrefix(nft.launcherId)}
          </Truncate>
        ),
      },
    ].filter(Boolean);

    let hexDIDId = undefined;
    let didId = undefined;
    let truncatedDID = undefined;

    if (nft.ownerDid) {
      hexDIDId = stripHexPrefix(nft.ownerDid);
      didId = didToDIDId(hexDIDId);
      truncatedDID = truncateValue(didId, {});
    }

    rows.push({
      key: 'ownerDid',
      label: <Trans>Owner DID</Trans>,
      value: nft.ownerDid ? (
        <Tooltip
          title={
            <Flex flexDirection="column" gap={1}>
              <Flex flexDirection="column" gap={0}>
                <Flex>
                  <Box flexGrow={1}>
                    <StyledTitle>DID ID</StyledTitle>
                  </Box>
                </Flex>
                <Flex alignItems="center" gap={1}>
                  <StyledValue>{didId}</StyledValue>
                  <CopyToClipboard value={didId} fontSize="small" invertColor />
                </Flex>
              </Flex>
              <Flex flexDirection="column" gap={0}>
                <Flex>
                  <Box flexGrow={1}>
                    <StyledTitle>DID ID (Hex)</StyledTitle>
                  </Box>
                </Flex>
                <Flex alignItems="center" gap={1}>
                  <StyledValue>{hexDIDId}</StyledValue>
                  <CopyToClipboard
                    value={hexDIDId}
                    fontSize="small"
                    invertColor
                  />
                </Flex>
              </Flex>
            </Flex>
          }
        >
          <Typography variant="body2">{truncatedDID}</Typography>
        </Tooltip>
      ) : (
        <Trans>Unassigned</Trans>
      ),
    });

    if (nft.ownerPubkey) {
      rows.push({
        key: 'ownerPubkey',
        label: <Trans>Owner Public Key</Trans>,
        value: (
          <Truncate ValueProps={{ variant: 'body2' }} tooltip copyToClipboard>
            {stripHexPrefix(nft.ownerPubkey)}
          </Truncate>
        ),
      });
    }

    rows.push({
      key: 'royaltyPercentage',
      label: <Trans>Royalty Percentage</Trans>,
      value: (
        <>
          {nft.royaltyPercentage ? (
            `${convertRoyaltyToPercentage(nft.royaltyPercentage)}%`
          ) : (
            <Trans>Unassigned</Trans>
          )}
        </>
      ),
    });

    if (!isLoadingMinterDID) {
      const truncatedDID = truncateValue(minterDID ?? '', {});

      rows.push({
        key: 'minterDID',
        label: <Trans>Minter DID</Trans>,
        value: minterDID ? (
          <Tooltip
            title={
              <Flex flexDirection="column" gap={1}>
                <Flex flexDirection="column" gap={0}>
                  <Flex>
                    <Box flexGrow={1}>
                      <StyledTitle>DID ID</StyledTitle>
                    </Box>
                  </Flex>
                  <Flex alignItems="center" gap={1}>
                    <StyledValue>{minterDID}</StyledValue>
                    <CopyToClipboard
                      value={minterDID}
                      fontSize="small"
                      invertColor
                    />
                  </Flex>
                </Flex>
                <Flex flexDirection="column" gap={0}>
                  <Flex>
                    <Box flexGrow={1}>
                      <StyledTitle>DID ID (Hex)</StyledTitle>
                    </Box>
                  </Flex>
                  <Flex alignItems="center" gap={1}>
                    <StyledValue>{minterHexDIDId}</StyledValue>
                    <CopyToClipboard
                      value={minterHexDIDId}
                      fontSize="small"
                      invertColor
                    />
                  </Flex>
                </Flex>
              </Flex>
            }
          >
            <Typography variant="body2">
              {minterDIDName ?? truncatedDID}
            </Typography>
          </Tooltip>
        ) : (
          <Trans>Unassigned</Trans>
        ),
      });
    }

    if (nft.mintHeight) {
      rows.push({
        key: 'mintHeight',
        label: <Trans>Minted at Block Height</Trans>,
        value: nft.mintHeight,
      });
    }

    if (dataUris?.length) {
      dataUris.forEach((uri, index) => {
        rows.push({
          key: `dataUri-${index}`,
          label: <Trans>Data URL {index + 1}</Trans>,
          value: (
            <Tooltip title={uri} copyToClipboard>
              <Typography variant="body2">{uri}</Typography>
            </Tooltip>
          ),
        });
      });
    }

    if (nft.dataHash) {
      rows.push({
        key: 'dataHash',
        label: <Trans>Data Hash</Trans>,
        value: (
          <Truncate ValueProps={{ variant: 'body2' }} tooltip copyToClipboard>
            {nft.dataHash}
          </Truncate>
        ),
      });
    }

    if (nft?.metadataUris?.length) {
      let index = 0;
      nft?.metadataUris.forEach((uri: string) => {
        if (uri) {
          rows.push({
            key: `metadataUris-${index}`,
            label: <Trans>Metadata URL {index + 1}</Trans>,
            value: (
              <Tooltip title={uri} copyToClipboard>
                <Typography variant="body2">{uri}</Typography>
              </Tooltip>
            ),
          });
          index++;
        }
      });
    }

    if (nft.metadataHash && nft.metadataHash !== '0x') {
      rows.push({
        key: 'metadataHash',
        label: <Trans>Metadata Hash</Trans>,
        value: (
          <Truncate ValueProps={{ variant: 'body2' }} tooltip copyToClipboard>
            {nft.metadataHash}
          </Truncate>
        ),
      });
    }

    if (nft?.licenseUris?.length) {
      let index = 0;
      nft?.licenseUris.forEach((uri: string) => {
        if (uri) {
          rows.push({
            key: `licenseUris-${index}`,
            label: <Trans>License URL {index + 1}</Trans>,
            value: (
              <Tooltip title={uri} copyToClipboard>
                <Typography variant="body2">{uri}</Typography>
              </Tooltip>
            ),
          });
          index++;
        }
      });
    }

    if (nft.licenseHash && nft.licenseHash !== '0x') {
      rows.push({
        key: 'licenseHash',
        label: <Trans>License Hash</Trans>,
        value: (
          <Truncate ValueProps={{ variant: 'body2' }} tooltip copyToClipboard>
            {nft.licenseHash}
          </Truncate>
        ),
      });
    }

    if (metadata?.preview_image_uris) {
      const value = metadata?.preview_image_uris.map(
        (uri: string, idx: number) => {
          return (
            <span>
              &nbsp;
              <Link href={uri} target="_blank">
                {uri}
              </Link>
            </span>
          );
        },
      );
      rows.push({
        key: 'preview_image_uris',
        label: <Trans>Preview image uris</Trans>,
        value,
      });
    }

    if (Array.isArray(metadata?.preview_video_uris)) {
      const value = metadata?.preview_video_uris.map(
        (uri: string, idx: number) => {
          return (
            <span>
              &nbsp;
              <Link target="_blank" href={uri}>
                {uri}
              </Link>
            </span>
          );
        },
      );
      rows.push({
        key: 'preview_video_uris',
        label: <Trans>Preview video uris</Trans>,
        value,
      });
    }

    return rows;
  }, [metadata, nft]);

  return (
    <Flex flexDirection="column" gap={1}>
      <Typography variant="h6">
        <Trans>Details</Trans>
      </Typography>

      <CardKeyValue rows={details} hideDivider />
    </Flex>
  );
}
