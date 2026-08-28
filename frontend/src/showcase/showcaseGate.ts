type ShowcaseRequest = {
  readonly isDevelopment: boolean
  readonly pathname: string
}

export function shouldRenderShowcase(request: ShowcaseRequest): boolean {
  return request.isDevelopment && request.pathname === "/__showcase"
}
