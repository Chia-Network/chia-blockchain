export default function isLocalhost(ip: string): boolean {
  return ip === '::1' || ip === '127.0.0.1';
}
