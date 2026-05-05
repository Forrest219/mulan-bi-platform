#!/usr/bin/env python3
"""
Standalone e2e test runner for T2.1 / T2.2 / T2.3.
Copies the test to a temp dir (app/ + services/ symlinked),
so conftest.py / alembic is completely out of scope.
"""
import os
import sys
import subprocess
import tempfile
import shutil

BACKEND = os.path.dirname(os.path.abspath(__file__))  # .../mulan-bi-platform/backend
PARENT  = os.path.dirname(BACKEND)                       # .../mulan-bi-platform

TEST    = os.path.join(BACKEND, "tests", "test_spec28_e2e_standalone.py")
assert os.path.exists(TEST), f"Test file not found: {TEST}"

ENV = {
    **os.environ,
    "PYTHONPATH": BACKEND,
    "DATABASE_URL": "postgresql://mulan:***@localhost:5432/mulan_bi_test",
    "SESSION_SECRET": "test-session-secret-for-ci-!!",
    "DATASOURCE_ENCRYPTION_KEY": "test-datasource-key-32-bytes-ok!!",
    "TABLEAU_ENCRYPTION_KEY": "test-tableau-key-32-bytes-ok!!",
    "LLM_ENCRYPTION_KEY": "test-llm-key-32-bytes-ok!!!!",
    "ADMIN_USERNAME": "admin",
    "ADMIN_PASSWORD": "",
    "SECURE_COOKIES": "false",
    "SERVICE_JWT_SECRET": "test-jwt-secret-for-service-auth-32ch",
    "HOMEPAGE_AGENT_MODE": "dual_write_with_insight",
}

# Create an isolated temp dir — no tests/ directory exists here
TMP = tempfile.mkdtemp(prefix="mulan_e2e_")

# Symlink app/ + services/ (resolve imports) + pytest.ini + test
os.makedirs(os.path.join(TMP, "app"))
os.makedirs(os.path.join(TMP, "services"))
os.symlink(os.path.join(BACKEND, "app", "main.py"), os.path.join(TMP, "app", "main.py"))

for subdir in ["api", "core", "models", "schemas"]:
    src = os.path.join(BACKEND, "app", subdir)
    if os.path.exists(src):
        os.symlink(src, os.path.join(TMP, "app", subdir))

for subdir in ["data_agent", "auth", "logs", "datasources", "llm", "tableau",
               "health_scan", "semantic_maintenance", "agent"]:
    src = os.path.join(BACKEND, "services", subdir)
    if os.path.exists(src):
        os.symlink(src, os.path.join(TMP, "services", subdir))

# Copy pytest.ini
with open(os.path.join(BACKEND, "pytest.ini")) as fh:
    content = fh.read()
with open(os.path.join(TMP, "pytest.ini"), "w") as fh:
    fh.write(content)

# Copy test to TMP
test_copy = os.path.join(TMP, "test_spec28_e2e_standalone.py")
shutil.copy2(TEST, test_copy)

# pyproject.toml so 'app' package is resolvable
with open(os.path.join(BACKEND, "pyproject.toml")) as fh:
    ptoml = fh.read()
with open(os.path.join(TMP, "pyproject.toml"), "w") as fh:
    fh.write(ptoml)

print(f"TMP dir : {TMP}")
print(f"PYTHONPATH={BACKEND}")

result = subprocess.run(
    [sys.executable, "-m", "pytest", test_copy, "-v", "--tb=short", "-p", "no:cacheprovider"],
    cwd=TMP,
    env=ENV,
)
print(f"\nExit code: {result.returncode}")
sys.exit(result.returncode)
