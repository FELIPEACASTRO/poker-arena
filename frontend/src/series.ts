export function boundedPoints<T>(points: readonly T[], maxPoints = 500): T[] {
  if (maxPoints <= 0 || points.length === 0) return []
  if (points.length <= maxPoints) return [...points]
  if (maxPoints === 1) return [points[0]]
  return Array.from({ length: maxPoints }, (_, index) => {
    const source = Math.round((index * (points.length - 1)) / (maxPoints - 1))
    return points[source]
  })
}
