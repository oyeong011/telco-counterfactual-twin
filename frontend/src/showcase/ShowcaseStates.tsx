import type { ReactNode } from "react"
import {
  PRIMITIVE_APPLICABLE_STATES,
  primitiveAnchor,
  type ShowcasePrimitive,
  type ShowcaseState,
} from "./primitiveStateRegistry"

type ShowcaseStateSectionProps = {
  readonly primitive: ShowcasePrimitive
  readonly description: string
  readonly children: (state: ShowcaseState) => ReactNode
}

export function ShowcaseStateSection({
  primitive,
  description,
  children,
}: ShowcaseStateSectionProps) {
  const anchor = primitiveAnchor(primitive)
  const states = PRIMITIVE_APPLICABLE_STATES[primitive]

  return (
    <section
      id={anchor}
      className="showcasePrimitive"
      aria-label={`${primitive} state gallery`}
      data-primitive={primitive}
    >
      <header className="showcaseSectionHeading">
        <p className="showcasePrimitiveKicker">
          Live primitive · {states.length} applicable states
        </p>
        <h2 id={`${anchor}-heading`}>{primitive}</h2>
        <p>{description}</p>
      </header>
      <div className="showcaseStateGrid" data-layout="state-grid">
        {states.map((state, index) => (
          <article
            className="showcaseStateCard"
            key={state}
            data-state={state}
            data-showcase-state={state}
          >
            <div className="showcaseStateCardHeader">
              <span className="showcaseStateLabel">{state}</span>
              <span className="showcaseStateIndex">{index + 1}</span>
            </div>
            <div className="showcaseStatePreview" data-preview={state}>
              {children(state)}
            </div>
          </article>
        ))}
      </div>
    </section>
  )
}
