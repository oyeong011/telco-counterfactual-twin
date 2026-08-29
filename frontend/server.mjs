import { createReadStream, statSync } from "node:fs"
import { createServer } from "node:http"
import { extname, join, normalize, resolve } from "node:path"

const root = resolve("dist")
const port = Number.parseInt(process.env.PORT ?? "8080", 10)

const contentTypes = new Map([
  [".css", "text/css; charset=utf-8"],
  [".html", "text/html; charset=utf-8"],
  [".js", "text/javascript; charset=utf-8"],
  [".json", "application/json; charset=utf-8"],
  [".svg", "image/svg+xml"],
])

function assetPath(url) {
  const pathname = new URL(url ?? "/", "http://localhost").pathname
  const candidate = resolve(root, normalize(pathname).replace(/^\/+/, ""))
  if (!candidate.startsWith(root)) return join(root, "index.html")
  try {
    return statSync(candidate).isFile() ? candidate : join(root, "index.html")
  } catch (error) {
    if (error instanceof Error && "code" in error && error.code === "ENOENT") {
      return join(root, "index.html")
    }
    throw error
  }
}

createServer((request, response) => {
  const file = assetPath(request.url)
  response.setHeader("Content-Type", contentTypes.get(extname(file)) ?? "application/octet-stream")
  createReadStream(file).pipe(response)
}).listen(port, "0.0.0.0")
