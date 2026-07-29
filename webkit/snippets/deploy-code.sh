#!/bin/bash
# Deploy museum *code* from rcmon (canonical repo) to bae_llm public mirror.
# Content (db snapshot + images) travels separately via museum-public-sync.sh.
# The bae venv (/opt/museum/.venv, excluded) only needs updating if the web
# app grows a new dependency - thumbs/ingest run on rcmon only.
set -e
rsync -a --delete --exclude .venv --exclude data --exclude .git \
  --exclude .playwright-mcp --exclude .pytest_cache \
  ~/museum/ bae_llm:/opt/museum/
ssh bae_llm "chown -R www-data:www-data /opt/museum && systemctl restart museum.service && sleep 1 && systemctl is-active museum.service"
