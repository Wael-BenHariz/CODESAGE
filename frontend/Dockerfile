# CodeSage Frontend Dockerfile (multi-stage: node build -> nginx)
#
# angular.json outputPath = "dist/codesage-frontend", builder =
# @angular-devkit/build-angular:application -> browser files land in
# dist/codesage-frontend/browser (verified with `npm run build`).

### Stage 1: builder
FROM node:20-alpine AS builder

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts

COPY . .
RUN npm run build -- --configuration production

### Stage 2: final (nginx alpine)
FROM nginx:alpine AS final

RUN rm -rf /usr/share/nginx/html/*

COPY --from=builder /app/dist/codesage-frontend/browser /usr/share/nginx/html

COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
