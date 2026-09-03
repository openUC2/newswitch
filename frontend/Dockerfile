FROM node:22-slim

# Run as the built-in `node` user (uid 1000). The codegen plugin WRITES generated sources
# back into /app/src, which compose bind-mounts from the host - as root those files come
# out root-owned and the host's own `yarn dev` can no longer rewrite them (EACCES).
# node:22-slim's `node` user is uid/gid 1000, which matches a typical Linux host user.
WORKDIR /app
RUN chown node:node /app
USER node

COPY --chown=node:node package.json yarn.lock ./
RUN yarn install --frozen-lockfile

COPY --chown=node:node . .

# Defaults matching the repo's root .env; compose overrides them per service.
# BACKEND_PORT is here because .env.docker expands ${BACKEND_PORT:-8099} into the
# schema URLs the codegen fetches at boot.
ENV FRONTEND_PORT=5173 \
    BACKEND_PORT=8099

# Documentation only, and resolved at BUILD time - a runtime -e FRONTEND_PORT still works,
# it just is not reflected here.
EXPOSE ${FRONTEND_PORT}

# Via `sh -c` so $FRONTEND_PORT is expanded rather than passed as a literal string,
# and `exec` so the signal path to yarn is not broken by an intermediate shell.
CMD ["sh", "-c", "exec yarn dev --mode docker --host 0.0.0.0 --port \"$FRONTEND_PORT\""]
