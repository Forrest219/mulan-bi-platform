#!/usr/bin/env python3
"""Startup wrapper that loads .env and runs uvicorn."""
import os, sys, subprocess

# Load .env
env_file = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(env_file):
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k] = v

# Ensure required vars (override with longer secrets if needed)
os.environ.setdefault("SESSION_SECRET", "dev-secret-for-local-32bytes!!")
os.environ.setdefault("DATABASE_URL", "postgresql://mulan:mulan@localhost:5432/mulan_bi")
os.environ.setdefault("DATASOURCE_ENCRYPTION_KEY", "dev-key-placeholder-32bytes!!")
os.environ.setdefault("TABLEAU_ENCRYPTION_KEY", "dev-key-placeholder-32bytes!!")
os.environ.setdefault("LLM_ENCRYPTION_KEY", "dev-key-placeholder-32bytes!!")
os.environ.setdefault("SERVICE_JWT_SECRET", "dev-service-jwt-secret-32bytes!!")

os.chdir(os.path.dirname(__file__) or ".")
sys.exit(subprocess.call([sys.executable, "-m", "uvicorn", "app.main:app", "--reload", "--port", "8000"]))
