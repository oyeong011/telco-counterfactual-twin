FROM node:26-alpine AS build
RUN npm install --global pnpm@11.19.0
WORKDIR /app
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml frontend/.npmrc frontend/
RUN pnpm --dir frontend install --frozen-lockfile
COPY frontend frontend
ARG VITE_API_BASE_URL=http://127.0.0.1:18080
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN pnpm --dir frontend build

FROM node:26-alpine
WORKDIR /app
COPY --chown=node:node frontend/server.mjs server.mjs
COPY --from=build --chown=node:node /app/frontend/dist dist
RUN chmod -R u=rwX,g=rX,o=rX /app/dist && chmod 0444 /app/server.mjs
USER node
EXPOSE 8080
CMD ["node", "server.mjs"]
