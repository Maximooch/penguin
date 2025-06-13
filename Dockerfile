# ---------------------------------------------------------------------------
# Phase 1: Base image and core dependencies
# ---------------------------------------------------------------------------
FROM python:3.11-slim as base

# Prevent Python from writing pyc files and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

WORKDIR /app

# Install build essentials and git
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install poetry for dependency management
RUN pip install "poetry==1.8.2"

# ---------------------------------------------------------------------------
# Phase 2: Install dependencies
# ---------------------------------------------------------------------------
FROM base as dependencies

# Copy only files required for dependency installation
COPY pyproject.toml poetry.lock* /app/

# Install project dependencies using poetry
# --no-root: don't install the project itself yet
# --no-dev: skip development dependencies
RUN poetry install --no-root --no-dev

# ---------------------------------------------------------------------------
# Phase 3: Build and package the application
# ---------------------------------------------------------------------------
FROM dependencies as builder

# Copy the rest of the application source code
COPY . /app/

# Install the application, now including any build scripts or other files
# This will install the `penguin` package into the virtual environment
RUN poetry install --no-dev

# ---------------------------------------------------------------------------
# Phase 4: Final, clean image
# ---------------------------------------------------------------------------
FROM base as final

# Copy the virtual environment with installed dependencies from the 'dependencies' stage
COPY --from=dependencies /app/.venv /.venv

# Copy the application code from the 'builder' stage
COPY --from=builder /app/ /app/

# Activate the virtual environment
ENV PATH="/app/.venv/bin:$PATH"

# Set the default command to launch a bash shell for interactive use
CMD ["bash"] 