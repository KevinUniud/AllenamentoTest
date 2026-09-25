FROM node:24.13.0-alpine@sha256:cd6fb7efa6490f039f3471a189214d5f548c11df1ff9e5b181aa49e22c14383e AS build

WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
# .dockerignore admits only source files needed by the static build.
COPY . .
RUN npm run build

FROM nginx:1.31.0-alpine@sha256:2f07d83bf561b506400dc183b1b2003803e39efbd22451f848adaba14d28c7c7

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
