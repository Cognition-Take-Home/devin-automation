# Container image for the dependency-automation app.
#
# Build:  docker build -t devin-automation .
# Run:    docker run --rm -e DEVIN_API_KEY -e DEVIN_ORG_ID \
#             -v "$PWD/state:/app/state" -v "/path/to/superset:/superset:ro" \
#             devin-automation check
FROM python:3.12-slim

# git: read the target repo / commit state.  gh: optional, powers the PR "rework" metric.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git gh ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies first (better layer caching), then the package itself.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir -e ".[dashboard]"

# The rest of the project (config, dashboard, scripts).
COPY . .

# Where the target repo (superset) is expected to be mounted, and where state persists.
ENV TARGET_REPO_PATH=/superset
VOLUME ["/app/state"]

ENTRYPOINT ["dep-automation"]
CMD ["check"]
