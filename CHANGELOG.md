# Changelog

All notable changes are documented here. The project follows Keep a Changelog
categories and Semantic Versioning.

## [Unreleased]

### Added

- Framework-neutral HTTP, OAuth 2.1, and MCP component packages.
- Modern MCP Streamable HTTP, MRTR, client cache/pagination, and legacy dialect adapter.

## Release process

1. Update this file and package versions in one reviewed change.
2. Tag the exact commit as `v<version>` after CI succeeds.
3. The protected `pypi` GitHub environment publishes the verified artifacts with trusted publishing.
4. Verify uploaded hashes and install each wheel in isolation before announcing the release.
