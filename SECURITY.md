# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 1.x.x   | :white_check_mark: |

## Reporting a Vulnerability

If you discover a security vulnerability within Mulan BI Platform, please send an email to the maintainer.

**Please do NOT report security vulnerabilities through public GitHub Issues.**

Instead, please report them via email. This allows us to:

1. Confirm the vulnerability and understand its scope
2. Develop and release a fix
3. Credit the reporter (if desired)

### What to Include

When reporting a vulnerability, please try to include:

- Type of vulnerability
- Full paths of source file(s) related to the vulnerability
- Location of the affected source code
- Any special configuration required to reproduce the issue
- Step-by-step instructions to reproduce the issue
- Proof-of-concept or exploit code (if possible)
- Impact of the issue

### Response Timeline

We aim to acknowledge vulnerability reports within 48 hours and will provide a more detailed response within 7 days with:

- Confirmation of the vulnerability
- Our planned release date for the fix
- Credit attribution (if desired)

## Security Best Practices for Deployment

When deploying Mulan BI Platform, please ensure:

- [ ] Set `SESSION_SECRET` to a strong, unique value in production
- [ ] Set `DATASOURCE_ENCRYPTION_KEY` to a strong, unique 32-byte value
- [ ] Use HTTPS in production environments
- [ ] Regularly update dependencies to patch known vulnerabilities
- [ ] Review access controls and permissions regularly
