# Mulan BI Platform

## Project Overview

Mulan BI Platform is a comprehensive data modeling and governance solution designed for BI teams to ensure data quality, consistency, and semantic integrity across the enterprise.

## Key Features

*   **DDL Specification Checks**: Enforce data definition language standards and best practices for database objects.
*   **Data Warehouse Health Scanning**: Proactively identify and report on potential issues within your data warehouse environment.
*   **Tableau Asset Governance**: Manage and maintain Tableau assets, ensuring semantic consistency and data lineage.
*   **LLM AI-Assisted Interpretation**: Leverage large language models to provide intelligent insights and explanations for data assets.
*   **Role-Based Access Control (RBAC)**: Implement granular permissions to secure data assets and platform functionalities.

## Quick Start

Follow these steps to get the Mulan BI Platform backend and its dependencies running quickly using Docker Compose.

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/your-org/mulan-bi-platform.git
    cd mulan-bi-platform
    ```

2.  **Start the PostgreSQL database:**
    ```bash
    cp .env.example .env
    docker-compose up -d
    ```

3.  **Install dependencies and run the backend application:**
    ```bash
    cd backend
    pip install -r requirements.txt
    alembic upgrade head
    uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
    ```
    The backend API will be accessible at `http://localhost:8000`.

## Architecture

Mulan BI Platform adopts a **Modular Monolith** architecture, providing a balance between development simplicity and maintainability for complex systems. The frontend and backend are decoupled, communicating via RESTful APIs.

The backend follows a **layered architecture** (API → Service → Data Access) to ensure clear separation of concerns and testability.

**Core Service Modules:**

*   `auth`: Handles user authentication, authorization, and session management.
*   `bi_core`: Manages core BI platform functionalities, including DDL checks and data warehouse health.
*   `ai_llm`: Integrates Large Language Models for AI-assisted data interpretation and insights.
*   `tableau_governance`: Provides specific functionalities for Tableau asset management and semantic maintenance.

## Tech Stack

### Frontend

*   **React 19**: A declarative, component-based JavaScript library for building user interfaces.
*   **TypeScript**: A strongly typed superset of JavaScript that enhances code quality and maintainability.
*   **Vite**: A next-generation frontend tooling that provides an extremely fast development experience.
*   **Tailwind CSS**: A utility-first CSS framework for rapidly building custom designs.

### Backend

*   **FastAPI**: A modern, fast (high-performance) web framework for building APIs with Python 3.7+ based on standard Python type hints.
*   **SQLAlchemy 2.x**: A powerful and flexible SQL toolkit and Object-Relational Mapper (ORM) for Python. Utilizes PostgreSQL 16 with JSONB fields and a robust connection pool (`pool_size=10, max_overflow=20`).
*   **PostgreSQL 16**: A powerful, open-source object-relational database system, serving as the primary data store.
*   **Alembic**: A lightweight database migration tool for usage with SQLAlchemy.
*   **Playwright**: A reliable end-to-end testing framework for modern web apps, used for robust integration tests.
*   **Authentication**: Implemented using Session/Cookie-based authentication, PBKDF2-SHA256 for password hashing, and JWT for secure token management.