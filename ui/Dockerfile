FROM nginxinc/nginx-unprivileged:1.27-alpine
# The base image ships stale Alpine packages; pull in the patched versions at build time.
USER root
RUN apk upgrade --no-cache && (apk del --no-cache nginx-module-xslt nginx-module-njs libxml2 libxslt || true)
COPY nginx.conf /etc/nginx/nginx.conf
COPY index.html /usr/share/nginx/html/index.html
USER 101
EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
