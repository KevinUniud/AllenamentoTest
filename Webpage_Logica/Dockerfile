FROM node:24.13.0-alpine@sha256:cd6fb7efa6490f039f3471a189214d5f548c11df1ff9e5b181aa49e22c14383e AS build

WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
# .dockerignore admits only source files needed by the static build.
COPY . .
RUN npm run build

FROM nginx:1.31.8-alpine@sha256:785835ea65db4bba6f021acc0f3be91b0fef76a53fe41f8588c6698d2aed0606

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
