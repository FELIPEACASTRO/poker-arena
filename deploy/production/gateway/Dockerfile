FROM node:22.17.0-alpine3.21 AS frontend-build
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
ENV VITE_API=/api
RUN npm run build

FROM nginx:1.30.2-alpine
RUN rm -f /etc/nginx/conf.d/default.conf \
    && mkdir -p /tmp/nginx-conf /tmp/nginx-cache \
    && chown -R 101:101 /tmp/nginx-conf /tmp/nginx-cache
COPY --from=frontend-build /src/dist /usr/share/nginx/html
COPY deploy/production/gateway/nginx.conf /etc/nginx/nginx.conf
COPY deploy/production/gateway/templates/default.conf.template /etc/nginx/templates/default.conf.template
COPY --chmod=0444 deploy/production/gateway/15-poker-secrets.envsh /docker-entrypoint.d/15-poker-secrets.envsh
USER 101:101
EXPOSE 8080 8443
