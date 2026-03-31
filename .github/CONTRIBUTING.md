# Contributing to Mulan BI Platform

Thank you for your interest in contributing to Mulan BI Platform!

## Development Workflow

### 1. Fork and Clone

```bash
git clone https://github.com/YOUR_USERNAME/mulan-bi-platform.git
cd mulan-bi-platform
```

### 2. Set Up Development Environment

```bash
# Install backend dependencies
pip install -r requirements.txt

# Set environment variables
cp .env.example .env
# Edit .env with your configuration

# Install frontend dependencies
cd frontend && npm install && cd ..
```

### 3. Start Development Servers

```bash
# Terminal 1: Backend
cd backend && uvicorn app.main:app --reload --port 8000

# Terminal 2: Frontend
cd frontend && npm run dev
```

### 4. Create a Feature Branch

```bash
git checkout -b feature/your-feature-name
# or
git checkout -b fix/your-bug-fix
```

## Commit Message Convention

Please follow conventional commit format:

- `feat:` New feature
- `fix:` Bug fix
- `docs:` Documentation only changes
- `style:` Changes that don't affect code meaning
- `refactor:` Code change that neither fixes a bug nor adds a feature
- `perf:` Performance improvement
- `test:` Adding or correcting tests
- `chore:` Maintenance tasks

Example:
```
feat(auth): add two-factor authentication support

- Add TOTP-based 2FA
- Add backup codes generation
- Update login flow UI
```

## Pull Request Process

### Before Submitting

1. Ensure all tests pass
2. Run linting:
   ```bash
   cd frontend && npm run lint
   ```
3. Update documentation if needed
4. Add tests for new functionality

### PR Description

Please include:

- **Summary**: What does this PR do?
- **Linked Issue**: `Closes #123` or `Implements #456`
- **Test Plan**: How was this tested?
- **Screenshots**: For UI changes

### PR Checklist

- [ ] Linked to related Issue/Discussion
- [ ] Documented steps to test
- [ ] Drafted "how to use" docs (if new behavior)
- [ ] Backwards compatibility considered
- [ ] Code follows project style guidelines

## Code Style

### Python (Backend)

- Follow PEP 8
- Use `snake_case` for functions and variables
- Use `PascalCase` for classes
- Add docstrings for public functions

### TypeScript/React (Frontend)

- Use PascalCase for components
- Use camelCase for functions and variables
- Use Chinese comments where appropriate for international team
- Prefer functional components with hooks

## Testing

```bash
# Run backend tests (when available)
pytest tests/

# Run frontend type check
cd frontend && npm run type-check
```

## License

By contributing to Mulan BI Platform, you agree that your contributions will be licensed under the MIT License.
