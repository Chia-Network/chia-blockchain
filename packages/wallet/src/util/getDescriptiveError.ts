import { t } from '@lingui/macro';

export default function getDescriptiveError(error: string): string {
  if (error == '13') {
    return t`[Error 13] Permission denied. You are trying to access a file/directory without having the necessary permissions. Most likely one of the plot folders in your config.yaml has an issue.`;
  }
  if (error == '22') {
    return t`[Error 22] File not found. Most likely one of the plot folders in your config.yaml has an issue.`;
  }

  return error;
}
