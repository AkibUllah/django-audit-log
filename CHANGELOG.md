# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-10-21

### Added

- `AuditEntry` model with actor, action, content type, object pk/repr, JSON field diff,
  IP, user agent, request id and timestamp.
- `audit_log.register(Model, fields=..., exclude=..., mask=...)` and the `@audited`
  decorator; signal receivers for create, update, delete and m2m changes.
- Sensitive-field masking (`mask=`) that records that a field changed without its value.
- `AuditMiddleware` capturing the current user, client IP (X-Forwarded-For aware),
  user agent and request id into a `contextvars`-based context; `audit_context()` and
  `disable_auditing()` context managers for commands and background jobs.
- Read-only admin with filters, search and a rendered diff.
- Optional DRF `AuditEntryViewSet` and serializer (`pip install django-audit-log[drf]`).
- `audit_prune` management command (`--days`, `--before`, `--model`, `--dry-run`).
- `bulk_update_audited()` and `bulk_delete_audited()` helpers for queryset operations
  that bypass model signals.
- Example project under `example/` and a pytest-django suite.
