---
title: Deployment
description: Deploy Orion in production environments
---

# Deployment

Orion supports multiple deployment strategies for different environments
and scales.

## Docker

The recommended way to deploy Orion in production. Multi-stage builds
with CPU and GPU (NVIDIA CUDA, AMD ROCm) variants.

[:octicons-arrow-right-24: Docker deployment](docker.md)

## systemd (Linux)

Run Orion as a managed system service on Linux servers.

[:octicons-arrow-right-24: systemd setup](systemd.md)

## launchd (macOS)

Register Orion as a launch agent on macOS.

[:octicons-arrow-right-24: launchd setup](launchd.md)

## API Server

Run Orion as an OpenAI-compatible HTTP server via `orion serve`.

[:octicons-arrow-right-24: API server guide](api-server.md)
