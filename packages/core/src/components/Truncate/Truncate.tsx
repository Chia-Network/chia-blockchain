import React from 'react';
import { Typography, TypographyProps } from '@mui/material';
import Tooltip from '../Tooltip';

/* ========================================================================== */

export type TruncateValueOptions = {
  separator?: string;
  leftLength?: number;
  rightLength?: number;
  splitSeparator?: string;
  prefixes?: string[];
};

export function truncateValue(
  children: string,
  opts: TruncateValueOptions
): string {
  const {
    separator = '...',
    leftLength = 4,
    rightLength = 4,
    splitSeparator = ':',
    prefixes = ['nft1', 'txch1', 'xch1', 'did:chia:1', '0x'],
  } = opts;

  if (!children) {
    return children;
  }

  const stringValue = children.toString();

  if (stringValue === 'did:chia:19qf3g9876t0rkq7tfdkc28cxfy424yzanea29rkzylq89kped9hq3q7wd2') {
    return 'Chia Network';
  }

  const parts = stringValue.split(splitSeparator);

  if (!parts.length) {
    return children;
  }

  // get last part and rest of the string
  const value = parts.pop();
  if (!value) {
    return children;
  }

  const rest = parts.join(splitSeparator);

  // skip prefix from truncation
  const prefixIndex = prefixes.findIndex(prefix => value.startsWith(prefix));
  const selectedPrefix = prefixIndex === -1 ? '' : prefixes[prefixIndex];
  const subValue =
    prefixIndex === -1 ? value : value.substring(selectedPrefix.length);

  const totalNewSize = leftLength + rightLength + separator.length;
  if (totalNewSize >= subValue.length + selectedPrefix.length) {
    return children;
  }

  const truncatedSubValue = `${subValue.substring(
    0,
    leftLength
  )}${separator}${subValue.substring(subValue.length - rightLength)}`;

  return rest
    ? `${rest}${splitSeparator}${selectedPrefix}${truncatedSubValue}`
    : `${selectedPrefix}${truncatedSubValue}`;
}

/* ========================================================================== */

export type TruncateProps = TruncateValueOptions & {
  children: string;
  tooltip?: boolean;
  copyToClipboard?: boolean;
  ValueProps?: TypographyProps;
};

export default function Truncate(props: TruncateProps) {
  const {
    tooltip,
    children,
    copyToClipboard = false,
    ValueProps,
    ...rest
  } = props;
  const value = truncateValue(children, rest);

  if (tooltip) {
    return (
      <Tooltip title={children} copyToClipboard={copyToClipboard}>
        <Typography {...ValueProps}>{value}</Typography>
      </Tooltip>
    );
  }

  return <Typography {...ValueProps}>{value}</Typography>;
}
