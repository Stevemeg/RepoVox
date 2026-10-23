FROM node:24.22.1-alpine@sha256:06d7adf3e0ef61a13f1d28682726366f97a15aa1888c934d3ecec86c33918b53 AS build
WORKDIR /web
COPY tools/security_node.mjs /security_node.mjs
RUN node /security_node.mjs
COPY apps/web/.npmrc ./
COPY apps/web/package*.json ./
RUN test "$(npm config get strict-ssl)" = true \
    && test "$(npm config get registry)" = https://registry.npmjs.org/ \
    && test "$(npm config get ca)" = null \
    && test "$(npm config get cafile)" = null \
    && npm ci
COPY apps/web ./
RUN npm run build
FROM node:24.22.1-alpine@sha256:06d7adf3e0ef61a13f1d28682726366f97a15aa1888c934d3ecec86c33918b53
WORKDIR /web
COPY tools/security_node.mjs /security_node.mjs
RUN node /security_node.mjs
ENV NODE_ENV=production PORT=3000 HOSTNAME=0.0.0.0
COPY --from=build --chown=node:node /web/.next/standalone ./
COPY --from=build --chown=node:node /web/.next/static ./.next/static
USER node
CMD ["node", "server.js"]
