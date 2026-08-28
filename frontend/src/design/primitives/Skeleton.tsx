import type { SkeletonVariant } from "./primitiveTypes"

type SkeletonProps = {
  readonly variant: SkeletonVariant
  readonly label: string
  readonly rows?: number
}

export function Skeleton({ variant, label, rows = 4 }: SkeletonProps) {
  const blocks = Array.from({ length: rows }, (_, index) => `${variant}-${index + 1}`)
  return (
    <div className="skeleton" data-variant={variant} role="status">
      <span>{label}</span>
      <div className="skeletonVisual" data-testid="skeleton-visual" aria-hidden="true">
        {blocks.map((block) => (
          <span className="skeletonBlock" key={block} />
        ))}
      </div>
    </div>
  )
}
