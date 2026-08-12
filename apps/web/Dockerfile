FROM node:24-alpine AS build
WORKDIR /app
ARG COREPACK_NPM_REGISTRY=https://registry.npmjs.org
RUN corepack enable
COPY package.json pnpm-lock.yaml* ./
ARG NPM_CONFIG_REGISTRY=https://registry.npmjs.org
RUN pnpm install --frozen-lockfile
COPY . .
RUN pnpm build

FROM node:24-alpine
WORKDIR /app
ENV NODE_ENV=production
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public
CMD ["node", "server.js"]
