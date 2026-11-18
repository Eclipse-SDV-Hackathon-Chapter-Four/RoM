# Security Policy

This project follows the [Eclipse Foundation Vulnerability Reporting Policy](https://www.eclipse.org/security/policy/).

## Reporting a vulnerability

Please do **not** report security vulnerabilities through public GitHub issues.

- Report privately through [GitHub Security Advisories](https://github.com/Eclipse-SDV-Hackathon-Chapter-Four/RoM/security/advisories/new) of this repository, or
- email the Eclipse Foundation Security Team at [security@eclipse-foundation.org](mailto:security@eclipse-foundation.org).

Include the affected component, steps to reproduce, and the impact you expect.

## Scope

This is a prototype / blueprint, not production software. The control and fault-injection APIs have no authentication
and listen on `127.0.0.1` only; do not expose them on a network.
