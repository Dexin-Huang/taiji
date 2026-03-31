# Security Policy

## Reporting a Vulnerability

**Do not open a public issue for security vulnerabilities.**

Please report security issues to the maintainer directly via GitHub private vulnerability reporting.

We will acknowledge your report within 48 hours and provide a detailed response within 5 business days.

## Scope

Taiji executes arbitrary Python code from `yin.py` and `yang.py` by design. The runtime assumes these files are trusted. Do not run untrusted unit definitions.
