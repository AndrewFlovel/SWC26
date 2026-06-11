# Stage 1: build the static bundle
FROM node:22-alpine AS build

WORKDIR /build

COPY package.json package-lock.json ./
RUN npm ci

# Empty API base makes the app call /api/* relative to its own origin;
# nginx (stage 2) proxies those calls to the backend service.
ARG VITE_API_BASE=""
ENV VITE_API_BASE=${VITE_API_BASE}

COPY . .
RUN npm run build

# Stage 2: serve with nginx, proxying /api to the backend container
FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /build/dist /usr/share/nginx/html

EXPOSE 80
