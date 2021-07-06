import normalize from 'normalize-url';

export default function normalizeUrl(url: string): string {
  return normalize(url, {
    defaultProtocol: 'https:',
    stripAuthentication: false,
    stripTextFragment: false,
    stripWWW: false,
    removeQueryParameters: false,
    removeTrailingSlash: false,
    removeSingleSlash: false,
    sortQueryParameters: false,
  });
}
