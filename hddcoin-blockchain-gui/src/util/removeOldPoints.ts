import type Point from '../types/Point';

const DAY_SECONDS = 60 * 60 * 24;

export default function removeOldPoints(
  points: Point[],
  second: number = DAY_SECONDS,
): Point[] {
  const current = Date.now() / 1000;
  const dayBefore = current - second;

  return points?.filter((point) => {
    const [timestamp] = point;

    return timestamp >= dayBefore;
  });
}
