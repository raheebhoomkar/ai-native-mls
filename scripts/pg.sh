# Shared by the backup scripts. Source it; do not run it.
#
# Postgres tools run from $PG_RUN when set (for example a `docker run` prefix in CI),
# else from PATH, else inside the docker-compose `postgres` container. Dumps travel
# through stdin and stdout, so no file has to be shared with a container.

pg() {
  if [ -n "${PG_RUN:-}" ]; then
    # shellcheck disable=SC2086  # PG_RUN is a command prefix and must split into words
    $PG_RUN "$@"
  elif command -v "$1" >/dev/null 2>&1; then
    "$@"
  else
    docker compose exec -T postgres "$@"
  fi
}

# SQLAlchemy URLs name the driver (postgresql+psycopg://); Postgres tools do not accept that.
plain_url() {
  local url="${1/postgresql+psycopg:/postgresql:}"
  echo "${url/postgres:\/\//postgresql://}"
}
