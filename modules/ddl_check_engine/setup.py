from setuptools import setup, find_packages

setup(
    name="ddl_check_engine",
    version="1.0.0",
    description="轻量级 DDL 规则引擎",
    author="Forrest219",
    author_email="forrest219@github.com",
    url="https://github.com/Forrest219/ddl_check_engine",
    packages=find_packages(),
    python_requires=">=3.8",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
    ],
)
