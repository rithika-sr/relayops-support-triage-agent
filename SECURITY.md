# Security policy

RelayOps is a local alpha intended for development and evaluation with synthetic data. It has not had an external
security review and is not supported for production use.

## Reporting a vulnerability

Please report suspected vulnerabilities privately through GitHub's "Report a vulnerability" (private security
advisory) on this repository. Include steps to reproduce, affected version or commit, and impact. Do not include real
personal data. You should receive an acknowledgement within a week.

## Scope

In scope: authentication, sessions and CSRF, tenant and customer-account isolation, approval binding and action
execution, agent tool scoping, prompt-injection handling, and secret handling in the repository.

## Security model

See [docs/security.md](docs/security.md) for the implemented controls and known gaps.
