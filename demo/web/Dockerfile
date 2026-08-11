FROM node:22-alpine AS build

WORKDIR /web
COPY demo/web/package.json demo/web/package-lock.json ./
RUN npm ci
COPY demo/web ./
RUN npm run build

FROM nginx:1.29-alpine
COPY demo/web/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /web/dist /usr/share/nginx/html
EXPOSE 80
