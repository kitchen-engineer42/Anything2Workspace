FROM python:3.12-slim AS base

# Install Node.js for repomix
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    npm install -g repomix && \
    apt-get purge -y curl && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -e .

# Create runtime directories
RUN mkdir -p input output output/chunks output/skus workspace logs/json logs/text

# Default environment
ENV INPUT_DIR=/app/input \
    OUTPUT_DIR=/app/output \
    LOG_DIR=/app/logs \
    WORKSPACE_DIR=/app/workspace

# Default command: show help
CMD ["bash"]
