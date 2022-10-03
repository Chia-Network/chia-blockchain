import React, { useMemo, ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import { useCopyToClipboard } from 'react-use';
import { Trans } from '@lingui/macro';
import type { NFTInfo } from '@chia/api';
import { useSetNFTStatusMutation } from '@chia/api-react';
import {
  AlertDialog,
  DropdownActions,
  MenuItem,
  useOpenDialog,
} from '@chia/core';
import {
  LinkSmall as LinkSmallIcon,
  NFTsSmall as NFTsSmallIcon,
  OffersSmall as OffersSmallIcon,
} from '@chia/icons';
import { ListItemIcon, Typography } from '@mui/material';
import {
  ArrowForward as TransferIcon,
  Cancel as CancelIcon,
  Link as LinkIcon,
  Download as DownloadIcon,
  PermIdentity as PermIdentityIcon,
  Visibility as VisibilityIcon,
  VisibilityOff as VisibilityOffIcon,
  DeleteForever as DeleteForeverIcon,
  Refresh as RefreshIcon,
} from '@mui/icons-material';
import { NFTTransferDialog, NFTTransferResult } from './NFTTransferAction';
import NFTOfferExchangeType from '../offers/NFTOfferExchangeType';
import NFTMoveToProfileDialog from './NFTMoveToProfileDialog';
import NFTSelection from '../../types/NFTSelection';
import useOpenUnsafeLink from '../../hooks/useOpenUnsafeLink';
import useHiddenNFTs from '../../hooks/useHiddenNFTs';
import useBurnAddress from '../../hooks/useBurnAddress';
import useViewNFTOnExplorer, {
  NFTExplorer,
} from '../../hooks/useViewNFTOnExplorer';
import isURL from 'validator/lib/isURL';
import download from '../../util/download';
import { stripHexPrefix } from '../../util/utils';
import NFTBurnDialog from './NFTBurnDialog';
import { useLocalStorage } from '@chia/core';
import computeHash from '../../util/computeHash';

/* ========================================================================== */
/*                          Common Action Types/Enums                         */
/* ========================================================================== */

export enum NFTContextualActionTypes {
  None = 0,
  CreateOffer = 1 << 0, // 1
  Transfer = 1 << 1, // 2
  MoveToProfile = 1 << 2, // 4
  CancelUnconfirmedTransaction = 1 << 3, // 8
  Hide = 1 << 4,
  Invalidate = 1 << 5,
  Burn = 1 << 6, // 16
  CopyNFTId = 1 << 7, // 32
  CopyURL = 1 << 8, // 64
  ViewOnExplorer = 1 << 9, // 128
  OpenInBrowser = 1 << 10, // 256
  Download = 1 << 11, // 512

  All = CreateOffer |
    Transfer |
    MoveToProfile |
    CancelUnconfirmedTransaction |
    CopyNFTId |
    CopyURL |
    ViewOnExplorer |
    OpenInBrowser |
    Download |
    Hide |
    Burn |
    Invalidate,
}

type NFTContextualActionProps = {
  selection?: NFTSelection;
};

/* ========================================================================== */
/*                             Copy NFT ID Action                             */
/* ========================================================================== */

type NFTCopyNFTIdContextualActionProps = NFTContextualActionProps;

function NFTCopyNFTIdContextualAction(
  props: NFTCopyNFTIdContextualActionProps,
) {
  const { selection } = props;
  const [, copyToClipboard] = useCopyToClipboard();
  const selectedNft: NFTInfo | undefined = selection?.items[0];
  const disabled = (selection?.items.length ?? 0) !== 1;

  function handleCopy() {
    if (!selectedNft) {
      throw new Error('No NFT selected');
    }

    copyToClipboard(selectedNft.$nftId);
  }

  return (
    <MenuItem onClick={handleCopy} disabled={disabled} close>
      <ListItemIcon>
        <NFTsSmallIcon />
      </ListItemIcon>
      <Typography variant="inherit" noWrap>
        <Trans>Copy NFT ID</Trans>
      </Typography>
    </MenuItem>
  );
}

/* ========================================================================== */
/*                             Create Offer Action                            */
/* ========================================================================== */

type NFTCreateOfferContextualActionProps = NFTContextualActionProps;

function NFTCreateOfferContextualAction(
  props: NFTCreateOfferContextualActionProps,
) {
  const { selection } = props;
  const navigate = useNavigate();
  const selectedNft: NFTInfo | undefined = selection?.items[0];
  const disabled =
    (selection?.items.length ?? 0) !== 1 || selectedNft?.pendingTransaction;

  function handleCreateOffer() {
    if (!selectedNft) {
      throw new Error('No NFT selected');
    }

    navigate('/dashboard/offers/create-with-nft', {
      state: {
        nft: selectedNft,
        exchangeType: NFTOfferExchangeType.NFTForToken,
        referrerPath: location.hash.split('#').slice(-1)[0],
      },
    });
  }

  return (
    <MenuItem onClick={handleCreateOffer} disabled={disabled} close>
      <ListItemIcon>
        <OffersSmallIcon />
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
  const { selection } = props;
  const openDialog = useOpenDialog();

  const selectedNft: NFTInfo | undefined = selection?.items[0];
  const disabled =
    (selection?.items.length ?? 0) !== 1 || selectedNft?.pendingTransaction;

  function handleComplete(result?: NFTTransferResult) {
    if (result) {
      if (result.success) {
        openDialog(
          <AlertDialog title={<Trans>NFT Transfer Pending</Trans>}>
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
    <MenuItem onClick={handleTransferNFT} disabled={disabled} close>
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
/*                           Move to Profile Action                           */
/* ========================================================================== */

type NFTMoveToProfileContextualActionProps = NFTContextualActionProps;

function NFTMoveToProfileContextualAction(
  props: NFTMoveToProfileContextualActionProps,
) {
  const { selection } = props;
  const openDialog = useOpenDialog();

  const selectedNft: NFTInfo | undefined = selection?.items[0];
  const disabled =
    (selection?.items.length ?? 0) !== 1 ||
    selectedNft?.pendingTransaction ||
    !selectedNft?.supportsDid;

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
      <NFTMoveToProfileDialog nft={selectedNft} onComplete={handleComplete} />,
    );
  }

  return (
    <MenuItem onClick={handleTransferNFT} disabled={disabled} close>
      <ListItemIcon>
        <PermIdentityIcon />
      </ListItemIcon>
      <Typography variant="inherit" noWrap>
        <Trans>Move to Profile</Trans>
      </Typography>
    </MenuItem>
  );
}

/* ========================================================================== */
/*                    Cancel Unconfirmed Transaction Action                   */
/* ========================================================================== */

type NFTCancelUnconfirmedTransactionContextualActionProps =
  NFTContextualActionProps;

function NFTCancelUnconfirmedTransactionContextualAction(
  props: NFTCancelUnconfirmedTransactionContextualActionProps,
) {
  const { selection } = props;
  const [setNFTStatus] = useSetNFTStatusMutation(); // Not really cancelling, just updating the status
  const openDialog = useOpenDialog();

  const selectedNft: NFTInfo | undefined = selection?.items[0];
  const disabled =
    (selection?.items.length ?? 0) !== 1 || !selectedNft?.pendingTransaction;

  async function handleCancelUnconfirmedTransaction() {
    const { error, data: response } = await setNFTStatus({
      walletId: selectedNft?.walletId,
      nftLauncherId: stripHexPrefix(selectedNft?.launcherId),
      nftCoinId: stripHexPrefix(selectedNft?.nftCoinId ?? ''),
      inTransaction: false,
    });
    const success = response?.success ?? false;
    const errorMessage = error ?? undefined;

    if (success) {
      openDialog(
        <AlertDialog title={<Trans>NFT Status Updated</Trans>}>
          <Trans>
            The NFT status has been updated. If the transaction was successfully
            sent to the mempool, it may still complete.
          </Trans>
        </AlertDialog>,
      );
    } else {
      const error = errorMessage || 'Unknown error';
      openDialog(
        <AlertDialog title={<Trans>NFT Status Update Failed</Trans>}>
          <Trans>The NFT status update failed: {error}</Trans>
        </AlertDialog>,
      );
    }
  }

  return (
    <MenuItem
      onClick={handleCancelUnconfirmedTransaction}
      disabled={disabled}
      divider
      close
    >
      <ListItemIcon>
        <CancelIcon />
      </ListItemIcon>
      <Typography variant="inherit" noWrap>
        <Trans>Cancel Unconfirmed Transaction</Trans>
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
  const { selection } = props;
  const openUnsafeLink = useOpenUnsafeLink();
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
    if (dataUrl) {
      openUnsafeLink(dataUrl);
    }
  }

  return (
    <MenuItem onClick={handleOpenInBrowser} disabled={disabled} close>
      <ListItemIcon>
        <LinkSmallIcon />
      </ListItemIcon>
      <Typography variant="inherit" noWrap>
        <Trans>Open in Browser</Trans>
      </Typography>
    </MenuItem>
  );
}

/* ========================================================================== */
/*                               Copy URL Action                              */
/* ========================================================================== */

type NFTCopyURLContextualActionProps = NFTContextualActionProps;

function NFTCopyURLContextualAction(props: NFTCopyURLContextualActionProps) {
  const { selection } = props;
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
    <MenuItem onClick={handleCopy} disabled={disabled} divider close>
      <ListItemIcon>
        <LinkIcon />
      </ListItemIcon>
      <Typography variant="inherit" noWrap>
        <Trans>Copy Media URL</Trans>
      </Typography>
    </MenuItem>
  );
}

/* ========================================================================== */
/*                          View on MintGarden Action                         */
/* ========================================================================== */

type NFTViewOnExplorerContextualActionProps = NFTContextualActionProps & {
  title?: string | JSX.Element;
  explorer: NFTExplorer;
};

function NFTViewOnExplorerContextualAction(
  props: NFTViewOnExplorerContextualActionProps,
) {
  const { selection, title, explorer } = props;
  const viewOnExplorer = useViewNFTOnExplorer();
  const selectedNft: NFTInfo | undefined = selection?.items[0];
  const disabled = !selectedNft;

  function handleView() {
    if (selectedNft) {
      viewOnExplorer(selectedNft, explorer);
    }
  }

  return (
    <MenuItem onClick={handleView} disabled={disabled} close>
      <ListItemIcon>
        <LinkSmallIcon />
      </ListItemIcon>
      <Typography variant="inherit" noWrap>
        {title}
      </Typography>
    </MenuItem>
  );
}

/* ========================================================================== */
/*                          Download file                                     */
/* ========================================================================== */

type NFTDownloadContextualActionProps = NFTContextualActionProps;

function NFTDownloadContextualAction(props: NFTDownloadContextualActionProps) {
  const { selection } = props;
  const selectedNft: NFTInfo | undefined = selection?.items[0];
  const disabled = !selectedNft;
  const dataUrl = selectedNft?.dataUris?.[0];

  function handleDownload() {
    if (!selectedNft) {
      return;
    }

    const dataUrl = selectedNft?.dataUris?.[0];
    if (dataUrl) {
      download(dataUrl);
    }
  }

  if (!dataUrl) {
    return null;
  }

  return (
    <MenuItem onClick={handleDownload} disabled={disabled} close>
      <ListItemIcon>
        <DownloadIcon />
      </ListItemIcon>
      <Typography variant="inherit" noWrap>
        <Trans>Download</Trans>
      </Typography>
    </MenuItem>
  );
}

/* ========================================================================== */
/*                          Hide NFT                                     */
/* ========================================================================== */

type NFTHideContextualActionProps = NFTContextualActionProps;

function NFTHideContextualAction(props: NFTHideContextualActionProps) {
  const { selection } = props;
  const selectedNft: NFTInfo | undefined = selection?.items[0];
  const disabled = !selectedNft;
  const dataUrl = selectedNft?.dataUris?.[0];
  const [isNFTHidden, setIsNFTHidden] = useHiddenNFTs();

  const isHidden = isNFTHidden(selectedNft);

  function handleToggle() {
    if (!selectedNft) {
      return;
    }

    setIsNFTHidden(selectedNft, !isHidden);
  }

  if (!dataUrl) {
    return null;
  }

  return (
    <MenuItem onClick={handleToggle} disabled={disabled} close>
      <ListItemIcon>
        {isHidden ? <VisibilityIcon /> : <VisibilityOffIcon />}
      </ListItemIcon>
      <Typography variant="inherit" noWrap>
        {isHidden ? <Trans>Show</Trans> : <Trans>Hide</Trans>}
      </Typography>
    </MenuItem>
  );
}

/* ========================================================================== */
/*                          Burn NFT                                     */
/* ========================================================================== */

type NFTBurnContextualActionProps = NFTContextualActionProps;

function NFTBurnContextualAction(props: NFTBurnContextualActionProps) {
  const { selection } = props;

  const openDialog = useOpenDialog();
  const burnAddress = useBurnAddress();

  const selectedNft: NFTInfo | undefined = selection?.items[0];
  const disabled =
    !selectedNft || !burnAddress || selectedNft?.pendingTransaction;
  const dataUrl = selectedNft?.dataUris?.[0];

  async function handleBurn() {
    if (!selectedNft) {
      return;
    }

    await openDialog(<NFTBurnDialog nft={selectedNft} />);
  }

  if (!dataUrl) {
    return null;
  }

  return (
    <MenuItem onClick={handleBurn} disabled={disabled} divider close>
      <ListItemIcon>
        <DeleteForeverIcon />
      </ListItemIcon>
      <Typography variant="inherit" noWrap>
        <Trans>Burn</Trans>
      </Typography>
    </MenuItem>
  );
}

/* ========================================================================== */
/*                     Invalidate cache of a single NFT                       */
/* ========================================================================== */

type NFTInvalidateContextualActionProps = NFTContextualActionProps;

function NFTInvalidateContextualAction(
  props: NFTInvalidateContextualActionProps,
) {
  const { selection } = props;

  const selectedNft: NFTInfo | undefined = selection?.items[0];
  const disabled = !selectedNft || selectedNft?.pendingTransaction;
  const dataUrl = selectedNft?.dataUris?.[0];
  const [, setThumbCache] = useLocalStorage(
    `thumb-cache-${selectedNft.$nftId}`,
    null,
  );
  const [, setContentCache] = useLocalStorage(
    `content-cache-${selectedNft.$nftId}`,
    null,
  );

  const [forceReloadNFT, setForceReloadNFT] = useLocalStorage(
    `force-reload-${selectedNft.$nftId}`,
    false,
  );

  const [, setMetadataCache] = useLocalStorage(
    `metadata-cache-${selectedNft.$nftId}`,
    {},
  );

  async function handleInvalidate() {
    if (!selectedNft) {
      return;
    }
    setThumbCache({});
    setContentCache({});
    setMetadataCache({});
    setForceReloadNFT(!forceReloadNFT);
    const ipcRenderer = (window as any).ipcRenderer;
    ipcRenderer.invoke(
      'removeCachedFile',
      computeHash(`${selectedNft.$nftId}_${dataUrl}`, { encoding: 'utf-8' }),
    );
  }

  if (!dataUrl) {
    return null;
  }

  return (
    <MenuItem
      onClick={() => {
        handleInvalidate();
      }}
      disabled={disabled}
      close
    >
      <ListItemIcon>
        <RefreshIcon />
      </ListItemIcon>
      <Typography variant="inherit" noWrap>
        <Trans>Refresh NFT data</Trans>
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
      [NFTContextualActionTypes.CopyNFTId]: {
        action: NFTCopyNFTIdContextualAction,
        props: {},
      },
      [NFTContextualActionTypes.CreateOffer]: {
        action: NFTCreateOfferContextualAction,
        props: {},
      },
      [NFTContextualActionTypes.Transfer]: {
        action: NFTTransferContextualAction,
        props: {},
      },
      [NFTContextualActionTypes.MoveToProfile]: {
        action: NFTMoveToProfileContextualAction,
        props: {},
      },
      [NFTContextualActionTypes.Invalidate]: {
        action: NFTInvalidateContextualAction,
        props: {},
      },
      [NFTContextualActionTypes.CancelUnconfirmedTransaction]: {
        action: NFTCancelUnconfirmedTransactionContextualAction,
        props: {},
      },

      [NFTContextualActionTypes.Hide]: {
        action: NFTHideContextualAction,
        props: {},
      },
      [NFTContextualActionTypes.Burn]: {
        action: NFTBurnContextualAction,
        props: {},
      },

      [NFTContextualActionTypes.ViewOnExplorer]: [
        {
          action: NFTViewOnExplorerContextualAction,
          props: {
            title: <Trans>View on MintGarden</Trans>,
            explorer: NFTExplorer.MintGarden,
          },
        },
        {
          action: NFTViewOnExplorerContextualAction,
          props: {
            title: <Trans>View on SkyNFT</Trans>,
            explorer: NFTExplorer.SkyNFT,
          },
        },
        {
          action: NFTViewOnExplorerContextualAction,
          props: {
            title: <Trans>View on Spacescan.io</Trans>,
            explorer: NFTExplorer.Spacescan,
          },
        },
      ],
      [NFTContextualActionTypes.OpenInBrowser]: {
        action: NFTOpenInBrowserContextualAction,
        props: {},
      },
      [NFTContextualActionTypes.CopyURL]: {
        action: NFTCopyURLContextualAction,
        props: {},
      },
      [NFTContextualActionTypes.Download]: {
        action: NFTDownloadContextualAction,
        props: {},
      },
    };

    return Object.keys(NFTContextualActionTypes)
      .map(Number)
      .filter(Number.isInteger)
      .filter((key) => actionComponents.hasOwnProperty(key))
      .filter((key) => availableActions & key)
      .map((key) => actionComponents[key])
      .flat();
  }, [availableActions]);

  return (
    <DropdownActions label={label} variant="outlined" {...rest}>
      {actions.map(({ action: Action, props: actionProps }, index) => (
        <Action
          key={`${index}-${actionProps?.title}`}
          selection={selection}
          {...actionProps}
        />
      ))}
    </DropdownActions>
  );
}
