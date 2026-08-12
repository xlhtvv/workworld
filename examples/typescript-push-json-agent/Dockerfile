FROM node:24-alpine

WORKDIR /app
COPY sdk/typescript/package.json ./sdk/typescript/package.json
COPY sdk/typescript/dist ./sdk/typescript/dist
COPY examples/typescript-push-json-agent/package.json ./examples/typescript-push-json-agent/package.json
COPY examples/typescript-push-json-agent/dist ./examples/typescript-push-json-agent/dist
WORKDIR /app/examples/typescript-push-json-agent
RUN mkdir -p node_modules/@workworld \
    && ln -s /app/sdk/typescript node_modules/@workworld/sdk
CMD ["node", "--enable-source-maps", "dist/server.js"]
