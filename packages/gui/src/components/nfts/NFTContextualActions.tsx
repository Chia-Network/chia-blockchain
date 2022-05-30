import React, { useMemo, ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import { useCopyToClipboard } from 'react-use';
import { Trans } from '@lingui/macro';
import type { NFTInfo } from '@chia/api';
import {
  AlertDialog,
  DropdownActions,
  useOpenDialog,
  useOpenExternal,
} from '@chia/core';
import type { DropdownActionsChildProps } from '@chia/core';
import { Offers as OffersIcon } from '@chia/icons';
import { ListItemIcon, MenuItem, Typography } from '@mui/material';
import {
  ArrowForward as TransferIcon,
  Link as LinkIcon,
  OpenInBrowser,
} from '@mui/icons-material';
import { NFTTransferDialog, NFTTransferResult } from './NFTTransferAction';
import NFTSelection from '../../types/NFTSelection';
import isURL from 'validator/lib/isURL';

/* ========================================================================== */
/*                          Common Action Types/Enums                         */
/* ========================================================================== */

export enum NFTContextualActionTypes {
  None = 0,
  CreateOffer = 1 << 0, // 1
  Transfer = 1 << 1, // 2
  OpenInBrowser = 1 << 2, // 4
  CopyURL = 1 << 3, // 8

  All = CreateOffer | Transfer | OpenInBrowser | CopyURL,
}

type NFTContextualActionProps = {
  onClose: () => void;
  selection?: NFTSelection;
};

/* ========================================================================== */
/*                             Create Offer Action                            */
/* ========================================================================== */

type NFTCreateOfferContextualActionProps = NFTContextualActionProps;

function NFTCreateOfferContextualAction(
  props: NFTCreateOfferContextualActionProps,
) {
  const { onClose, selection } = props;
  const navigate = useNavigate();
  const selectedNft: NFTInfo | undefined = selection?.items[0];
  const disabled = (selection?.items.length ?? 0) !== 1;

  function handleCreateOffer() {
    if (!selectedNft) {
      throw new Error('No NFT selected');
    }

    navigate('/dashboard/offers/create-with-nft', {
      state: {
        nft: selectedNft,
        referrerPath: location.hash.split('#').slice(-1)[0],
      },
    });
  }

  return (
    <MenuItem
      onClick={() => {
        onClose();
        handleCreateOffer();
      }}
      disabled={disabled}
    >
      <ListItemIcon>
        <OffersIcon />
      </ListItemIcon>
      <Typography variant="inherit" noWrap>
        <Trans>Create Offer</Trans>
      </Typography>
    </MenuItem>
  );
}

/* ========================================================================== */
/*                             Transfer NFT Action                            */
/* ========================================================================== */

type NFTTransferContextualActionProps = NFTContextualActionProps;

function NFTTransferContextualAction(props: NFTTransferContextualActionProps) {
  const { onClose, selection } = props;
  const openDialog = useOpenDialog();
  const selectedNft: NFTInfo | undefined = selection?.items[0];
  const disabled = (selection?.items.length ?? 0) !== 1;

  function handleComplete(result?: NFTTransferResult) {
    if (result) {
      if (result.success) {
        openDialog(
          <AlertDialog title={<Trans>NFT Transfer Complete</Trans>}>
            <Trans>
              The NFT transfer transaction has been successfully submitted to
              the blockchain.
            </Trans>
          </AlertDialog>,
        );
      } else {
        const error = result.error || 'Unknown error';
        openDialog(
          <AlertDialog title={<Trans>NFT Transfer Failed</Trans>}>
            <Trans>The NFT transfer failed: {error}</Trans>
          </AlertDialog>,
        );
      }
    }
  }

  function handleTransferNFT() {
    openDialog(
      <NFTTransferDialog nft={selectedNft} onComplete={handleComplete} />,
    );
  }

  return (
    <MenuItem
      onClick={() => {
        onClose();
        handleTransferNFT();
      }}
      disabled={disabled}
    >
      <ListItemIcon>
        <TransferIcon />
      </ListItemIcon>
      <Typography variant="inherit" noWrap>
        <Trans>Transfer NFT</Trans>
      </Typography>
    </MenuItem>
  );
}

/* ========================================================================== */
/*                       Open Data URL in Browser Action                      */
/* ========================================================================== */

type NFTOpenInBrowserContextualActionProps = NFTContextualActionProps;

function NFTOpenInBrowserContextualAction(
  props: NFTOpenInBrowserContextualActionProps,
) {
  const { onClose, selection } = props;
  const openExternal = useOpenExternal();
  const selectedNft: NFTInfo | undefined = selection?.items[0];
  const haveDataUrl = selectedNft?.dataUris?.length && selectedNft?.dataUris[0];
  const dataUrl: string | undefined = haveDataUrl
    ? selectedNft.dataUris[0]
    : undefined;
  const isUrlValid = useMemo(() => {
    if (!dataUrl) {
      return false;
    }

    return isURL(dataUrl);
  }, [dataUrl]);
  const disabled = !haveDataUrl || !isUrlValid;

  function handleOpenInBrowser() {
    openExternal(dataUrl);
  }

  return (
    <MenuItem
      onClick={() => {
        onClose();
        handleOpenInBrowser();
      }}
      disabled={disabled}
    >
      <ListItemIcon>
        <OpenInBrowser />
      </ListItemIcon>
      <Typography variant="inherit" noWrap>
        <Trans>Open in Web Browser</Trans>
      </Typography>
    </MenuItem>
  );
}

/* ========================================================================== */
/*                               Copy URL Action                              */
/* ========================================================================== */

type NFTCopyURLContextualActionProps = NFTContextualActionProps;

function NFTCopyURLContextualAction(props: NFTCopyURLContextualActionProps) {
  const { onClose, selection } = props;
  const [, copyToClipboard] = useCopyToClipboard();
  const selectedNft: NFTInfo | undefined = selection?.items[0];
  const haveDataUrl = selectedNft?.dataUris?.length && selectedNft?.dataUris[0];
  const dataUrl: string | undefined = haveDataUrl
    ? selectedNft.dataUris[0]
    : undefined;
  const disabled = !haveDataUrl;

  function handleCopy() {
    if (dataUrl) {
      copyToClipboard(dataUrl);
    }
  }

  return (
    <MenuItem
      onClick={() => {
        onClose();
        handleCopy();
      }}
      disabled={disabled}
    >
      <ListItemIcon>
        <LinkIcon />
      </ListItemIcon>
      <Typography variant="inherit" noWrap>
        <Trans>Copy URL</Trans>
      </Typography>
    </MenuItem>
  );
}

/* ========================================================================== */
/*                             Contextual Actions                             */
/* ========================================================================== */

type NFTContextualActionsProps = {
  label?: ReactNode;
  selection?: NFTSelection;
  availableActions?: NFTContextualActionTypes;
  toggle?: ReactNode;
};

export default function NFTContextualActions(props: NFTContextualActionsProps) {
  const {
    label = <Trans>Actions</Trans>,
    selection,
    availableActions = NFTContextualActionTypes.CreateOffer |
      NFTContextualActionTypes.Transfer,
    ...rest
  } = props;

  const actions = useMemo(() => {
    const actionComponents = {
      [NFTContextualActionTypes.CreateOffer]: NFTCreateOfferContextualAction,
      [NFTContextualActionTypes.Transfer]: NFTTransferContextualAction,
      [NFTContextualActionTypes.OpenInBrowser]:
        NFTOpenInBrowserContextualAction,
      [NFTContextualActionTypes.CopyURL]: NFTCopyURLContextualAction,
    };

    return Object.keys(NFTContextualActionTypes)
      .map(Number)
      .filter(Number.isInteger)
      .filter((key) => actionComponents.hasOwnProperty(key))
      .filter((key) => availableActions & key)
      .map((key) => actionComponents[key]);
  }, [availableActions]);

  return (
    <DropdownActions label={label} variant="outlined" {...rest}>
      {({ onClose }: DropdownActionsChildProps) => (
        <>
          {actions.map((Action) => (
            <Action onClose={onClose} selection={selection} />
          ))}
        </>
      )}
    </DropdownActions>
  );
}
