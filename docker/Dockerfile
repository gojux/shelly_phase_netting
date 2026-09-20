# Test image: a chosen Python version with a chosen (default: latest) Home Assistant.
ARG PYTHON_VERSION=3.14
FROM python:${PYTHON_VERSION}-slim

# Empty HA_VERSION installs the latest release; PIP_PRE=1 also considers pre-releases (beta).
ARG HA_VERSION=
ARG PIP_PRE=

ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# Compilers for dependencies that ship no wheel for the chosen Python version.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libffi-dev libssl-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements_test.txt /tmp/requirements_test.txt
RUN pip install ${PIP_PRE:+--pre} ${HA_VERSION:+"homeassistant==${HA_VERSION}"} -r /tmp/requirements_test.txt

COPY docker/run_tests.sh /usr/local/bin/run-tests
RUN chmod +x /usr/local/bin/run-tests

WORKDIR /workspace
ENTRYPOINT ["run-tests"]
