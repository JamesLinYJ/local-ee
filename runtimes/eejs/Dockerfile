FROM node:24-alpine@sha256:44fce696f38ba8c987c4db89954051000bbd05ffd8d8659ba15ed4a8602e937f
RUN apk upgrade --no-cache && mkdir -p /opt/eejs/vendor /job && chown node:node /job
COPY vendor/earthengine-js /opt/eejs/vendor
COPY runtimes/eejs/*.cjs /opt/eejs/
ENV HOME=/tmp NODE_ENV=production NODE_OPTIONS=--disable-proto=throw
WORKDIR /tmp
USER 1000:1000
ENTRYPOINT ["node", "/opt/eejs/runner.cjs"]
