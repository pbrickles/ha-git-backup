# Changelog

## Unreleased

### Added

- Git-tracked file ownership manifest with mode/content fingerprints and explicit, fingerprint-bound adoption approvals.
- Migration, manifest corruption, scoped deletion, source failure, path collision, fresh-clone, and Git conflict regressions.

### Changed

- Replace repository-wide rsync deletion with staged copying and exact, verified managed-file deletions.
- Preserve all unowned repository files, including matches of explicit exclusions; reserve OpenSpec and backup metadata alongside workflows and ignore rules.
- Refuse conflicting adoptions, independent Git edits, and unsafe file/directory replacements before applying the backup plan.
- Serialize backup triggers while retaining branch synchronization and pending-push retries.

### Fixed

- Switch to the configured backup branch and integrate remote advances before copying configuration.
- Merge divergence without rewriting history; abort on conflicts, unfinished Git operations, or uncommitted changes.
- Retry outstanding pushes even when a backup produces no new commit.
- Use repository-local author identity and an explicit global Git configuration path when HOME is absent.

## [1.0.14-test.2] - 2026-10-14

### Fixed

- Preserve repository-owned `.github/` workflows against synchronization deletion and source overwrites.
- Add regression coverage for repository-managed workflows and `.gitignore` across empty and broad allowlists.

## [1.0.14-test.1] - 2026-10-14

### Fixed

- Enforce configured file filters, with exclusions taking precedence and nested directory inclusion.
- Remove previously backed-up excluded files without changing source files or Git history.
- Preserve repository ignore rules and abort before staging on synchronization failure.

### Added

- Local integration tests and Linux CI for filtering and deletion behavior.

### Changed

- Test fork builds locally in Home Assistant instead of installing upstream container images.
- Remove the conflicting default `.storage/*` user exclusion; built-in storage protection remains.

## [1.0.13] - 2025-01-21

### Fixed

- Fix git author identity: default `commit_user_email` to "homeassistant@local" instead of empty
- Add fallback in shell script for empty name/email values

## [1.0.12] - 2025-01-21

### Fixed

- Mask SSH private key in UI (changed schema from `str` to `password`)

## [1.0.11] - 2025-01-21

### Added

- `watch_burst_limit` option: allow N rapid backups before backing off (default 5)

### Fixed

- Backoff logic: only triggers after actual backup, not on every file event
- Backoff now properly resets after calm period (4× min interval)

### Changed

- Improved log messages: shows filename in change detection

## [1.0.10] - 2025-01-21

### Changed

- Comprehensive documentation rewrite with full configuration reference
- Added example configurations for common use cases
- Documented API endpoints, troubleshooting, and security considerations

## [1.0.9] - 2025-01-21

### Added

- Exponential backoff for file watcher to prevent infinite commit loops
- New config options: `watch_min_interval` (default 30s) and `watch_max_interval` (default 30min)

### Changed

- Renamed `watch_debounce_seconds` to `watch_min_interval`
- When rapid changes are detected, interval doubles up to max (30min default)

## [1.0.8] - 2025-01-21

### Changed

- Improved commit messages: now include file names summary (e.g., "Backup: configuration.yaml, automations.yaml (+2 more)")
- New `{files}` placeholder for commit message template
- Default commit message changed from "Automated backup: {date}" to "Backup: {files}"

## [1.0.7] - 2025-01-05

### Changed

- Exclude entire .storage/ directory, whitelist lovelace dashboards and core.config

## [1.0.6] - 2025-01-05

### Changed

- Exclude .storage/core.*_registry and core.restore_state by default

## [1.0.4] - 2025-01-05

### Fixed

- Fixed copy button with fallback for non-secure contexts

## [1.0.3] - 2025-01-05

### Fixed

- Fixed Web UI API calls to use relative paths for ingress compatibility

## [1.0.2] - 2025-01-05

### Fixed

- Fixed Dockerfile chmod failing on non-existent directory
- Fixed run.sh permissions

## [1.0.1] - 2025-01-05

### Added

- Git logo for add-on
- SSH public key saved to /share/git_backup_ssh_key.pub
- Web UI for viewing SSH key and triggering backups

### Fixed

- Removed invalid default email address

## [1.0.0] - 2025-01-05

### Added

- Initial release
- Automatic scheduled backups to Git repository
- HTTPS authentication with username/password or token
- SSH key authentication
- Configurable backup interval
- Smart default exclusions (databases, logs, cache)
- Configurable include/exclude patterns
- Support for GitHub, GitLab, Bitbucket, and self-hosted Git
