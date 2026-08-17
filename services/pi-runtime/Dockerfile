FROM node:22.22-alpine

ENV NODE_ENV=production \
    PORT=8765

RUN addgroup -S -g 10004 pi && adduser -S -u 10004 -G pi -h /app pi
WORKDIR /app

COPY services/pi-runtime/package.json services/pi-runtime/package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts && npm cache clean --force

COPY services/pi-runtime/src ./src
USER pi

EXPOSE 8765
CMD ["node", "src/server.mjs"]
