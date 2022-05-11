import { Typography } from '@mui/material';
import Tooltip from '../Tooltip';

function parseValue(props) {
  const {
    children,
    separator = '...',
    leftLength = 4,
    rightLength = 4,
    splitSeparator = ':',
    prefixes = ['nft1', 'nft0', 'xch', 'txch'],
  } = props;

  if (!children) {
    return children;
  }

  const parts = children.toString().split(splitSeparator);
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
  const subValue = prefixIndex === -1 ? value : value.substring(selectedPrefix.length);

  const totalNewSize = leftLength + rightLength + separator.length;
  if (totalNewSize >= (subValue.length + selectedPrefix.length)) {
    return children;
  }

  const truncatedSubValue = `${subValue.substring(0, leftLength)}${separator}${subValue.substring(subValue.length - rightLength)}`;

  return rest
    ? `${rest}${splitSeparator}${selectedPrefix}${truncatedSubValue}`
    : `${selectedPrefix}${truncatedSubValue}`;
}

export type TruncateProps = {
  children: string;
  separator?: string;
  leftLength?: number;
  rightLength?: number;
  splitSeparator?: string;
  prefixes?: string[];
  tooltip?: boolean;
  copyToClipboard?: boolean;
};

export default function Truncate(props: TruncateProps) {
  const { tooltip, children, copyToClipboard = false } = props;
  const value = parseValue(props);

  if (tooltip) {
    return (
      <Tooltip title={children} copyToClipboard={copyToClipboard}>
        <Typography>
          {value}
        </Typography>
      </Tooltip>
    );
  }

  return value;
}
