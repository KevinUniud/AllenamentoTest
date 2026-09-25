FROM node:26.9.0-alpine@sha256:dbaa92e5758cbbcf85d65d5403fdb530fe3442cbe8c6dbfb7ef23365450d5070 AS build

WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
# .dockerignore admits only source files needed by the static build.
COPY . .
RUN npm run build

FROM nginx:1.30.4-alpine@sha256:97d490c12ba55b4946b01546d1c3ed324e8d41ab1c9fcb2a616aa470620e5b46

# Only the verified static export is public; Node and source files stay in build.
RUN rm -rf /usr/share/nginx/html/*
COPY --from=build /app/out/ /usr/share/nginx/html/
COPY --from=build /app/.build/csp-map.conf /etc/nginx/csp-map.conf
COPY --from=build /app/.build/legacy-routes.conf /etc/nginx/legacy-routes.conf
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY nginx/security-headers.conf /etc/nginx/security-headers.conf

ENV API_UPSTREAM=http://host.docker.internal:5000 \
    API_PROXY_TIMEOUT_SECONDS=125 \
    FEEDBACK_UPSTREAM=http://feedback:5555 \
    FEEDBACK_CHARTS_REFRESH_SECONDS=300

EXPOSE 80
