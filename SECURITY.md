# Security Policy

## Supported Versions

We support the latest release of Dossier with security updates. If you run an older version, please upgrade when possible.

| Version | Supported          |
| ------- | ------------------ |
| latest  | :white_check_mark: |
| older   | :x:                |

## Reporting a Vulnerability

If you discover a security vulnerability, please report it responsibly:

1. **Do not** open a public issue for security vulnerabilities.
2. **Open a private security advisory** on GitHub: [https://github.com/etorhub/dossier/security/advisories/new](https://github.com/etorhub/dossier/security/advisories/new)
3. Provide a clear description of the issue, steps to reproduce, and any suggested mitigations.

We will acknowledge your report and work with you to understand and address the vulnerability. We aim to respond within 7 days and will keep you updated on progress.

## What We Care About

- Authentication and authorization bypasses
- SQL injection or other database access issues
- Exposure of sensitive data (e.g. `.env`, passwords, API keys)
- Cross-site scripting (XSS) or request forgery (CSRF)
- Privilege escalation (e.g. admin access without authorization)
- Issues in dependencies that affect this project

## Out of Scope

- Issues in Ollama or other external services we integrate with (report to those projects)
- Theoretical vulnerabilities without a practical exploit path
- Social engineering or physical access attacks

## Acknowledgments

We thank security researchers who report vulnerabilities responsibly. Contributors who help improve security will be acknowledged (with their permission) in release notes or a dedicated acknowledgments section.
