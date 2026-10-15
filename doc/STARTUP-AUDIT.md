# Startup behavior audit

Compared on 2026-10-14:

- Upstream `sttts/ha-git-backup` main: `9a576c53e67db407735b501720072d71399ce9a5` (verified with `git ls-remote`).
- Test fork implementation: `2cbee1931d004a820a750ab6c7dc6c467ace622f` (`1.0.14-test.2`).

## Finding

The filtering changes did not introduce or alter the startup backup. The complete
configuration-loading and authentication/repository-setup section, and the
complete `main()` function, scheduling, and cleanup section, are identical to
upstream.

Both versions call `do_backup "startup"` behind the same condition:

```bash
if [ "$BACKUP_ON_START" = "true" ]; then
    log_info "Performing initial backup..."
    do_backup "startup" || log_warn "Initial backup failed"
fi
```

However, the existing configuration helper uses jq's alternative operator:

```bash
jq -r ".$key // \"$default\"" "$CONFIG_PATH"
```

For `backup_on_start`, the default is the string `"true"`. jq's `//` selects the
alternative for both `null` and `false`, so an explicit JSON boolean `false`
becomes `"true"`. Thus, when a repository is configured and setup succeeds, both
versions attempt an initial backup even when `backup_on_start` is false. This is
an existing upstream configuration-loading bug, not a filtering regression.

## Verification

A temporary-directory Bash harness extracted the actual `get_config()` and
`main()` functions from each version. SSH setup, repository setup, Web UI,
logging, status updates, and manual triggers were stubbed. `do_backup()` recorded
its trigger; the first sleep exited the harness before the indefinite main loop.
No authentication, network connection, or real backup was performed.

| Configured value | Upstream loaded value / trigger | Fork loaded value / trigger |
| --- | --- | --- |
| `true` | `true` / `startup` | `true` / `startup` |
| `false` | `true` / `startup` | `true` / `startup` |

Both runs produced identical results. No startup or authentication changes were
made, and no permanent test was added to lock in this unrelated upstream bug.

## Proposed upstream PR scope

Keep the upstream PR limited to rsync inclusion/exclusion selection, deletion of
previously tracked excluded files, required protection of repository-owned Git
metadata, root `.github/`, and root `.gitignore`, plus associated tests, test CI,
filtering documentation, translated option descriptions, and removal of the
conflicting default `.storage/*` exclusion.

Do not include a fix to `get_config()`, startup scheduling, or authentication.
The test fork's repository metadata, branding, source-build configuration,
prerelease version/changelog, installation README banner, and this audit are
fork-only material and should be omitted from the upstream PR. In particular,
restore upstream name, URL, image configuration, and build-source label when
preparing the upstream patch; retain only filtering-related config changes.
