export function calculateSizeFromK(k) {
  return Math.floor(780 * k * Math.pow(2, k - 10));
}
