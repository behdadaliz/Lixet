# Lixet

Lixet is a deterministic Linux configuration diagnosis and repair CLI. It reads known configuration files, runs trusted local validation tools when they are available, and explains the problems it can prove.

Automatic repair is deliberately narrow. Lixet does not use AI, guess a desired policy, restart services, change firewall rules, mount filesystems, or apply sysctl values.

> **Status:** `v0.2.2-beta` is a controlled beta release for testing on disposable Linux systems. It is not recommended for production systems yet.

## Install

Lixet requires Linux and Python 3.10 or newer.

```bash
git clone https://github.com/behdadaliz/Lixet.git
cd Lixet
sudo sh install.sh
```

The installer creates an owned installation under `/opt/lixet` and exposes the `lixet` command through `/usr/local/bin/lixet`. It refuses to replace unrelated entries unless `--force` is explicitly passed.

To uninstall an installation owned by Lixet:

```bash
sudo sh uninstall.sh
```

## Commands

```bash
lixet                           # Show help
lixet services                  # List supported services
lixet scan ssh                  # Scan one service
lixet scan ssh --dry-run        # Preview available repairs
lixet scan ssh -y               # Apply proven safe repairs only
lixet doctor                    # Scan every supported service
lixet doctor --dry-run          # Preview repairs from doctor
lixet doctor -y                 # Apply proven safe repairs only
lixet --version                 # Show installed and latest release versions
sudo lixet --update             # Install a newer trusted release
lixet --no-color scan ssh       # Disable ANSI colors
```

Only `scan` accepts a custom configuration path:

```bash
lixet scan nginx --config /path/to/nginx.conf
```

`doctor --config` is rejected because one file must never be interpreted by unrelated validators.

## Supported Services

`lixet services` prints the live service registry and short descriptions. The current names are:

- `ssh`: OpenSSH server configuration and includes
- `nginx`: root configuration and includes
- `ufw`: state, defaults, and runtime status
- `dns`: resolver syntax and local manager state
- `networking`: `/etc/hosts` and local network state
- `systemd`: runtime state, local units, and drop-ins
- `sudoers`: syntax through `visudo`
- `fstab`: syntax through `findmnt`
- `sysctl`: load order and effective overrides

Aliases include `sshd` and `openssh` for `ssh`, `hosts` and `network` for `networking`, and `firewall` for `ufw`.

## Repairs

Every finding has one repair level:

- **safe**: a small deterministic edit covered by focused tests; `-y` may approve it.
- **guarded**: a sensitive exact-line edit that requires an interactive terminal and typing `APPLY`; `-y` skips it.
- **report-only**: no automatic edit is offered because system policy or intent cannot be proven.

The safe repairs currently restore missing standard localhost entries or the `localhost` token in `/etc/hosts`. Exact directives rejected by `sshd` in SSH configuration, and exact invalid lines in included sudoers files, may be offered as guarded repairs. Most SSH policy, Nginx, DNS, UFW, systemd, fstab, and sysctl findings are report-only.

Before a write, Lixet checks that the inspected file still has the same path, symlink state, device, inode, size, timestamp, content hash, mode, owner, and group. A repair transaction then:

1. previews every exact edit;
2. creates a protected backup under `/var/lib/lixet/backups`;
3. locks the affected paths;
4. writes atomically without replacing a supported symlink object;
5. re-inspects and re-validates the result;
6. runs the required external verifier for SSH, Nginx, sudoers, fstab, or systemd repairs;
7. rolls back every changed file if validation fails or the operation is interrupted.

There is no user-facing restore command yet. Backup restore exists as a tested internal API; keep backup bundles intact.

Managed resolver links, including common systemd-resolved, NetworkManager, and resolvconf setups, are detected and left report-only. Broken, cyclic, unreadable, or changing targets are rejected.

## Permissions And Offline Behavior

Read-only scans can run without root when the relevant files and commands are accessible. Repairing protected system files normally requires `sudo`. Installation, uninstallation, and update require Linux root privileges.

Normal scans do not make external DNS or internet requests. `lixet --version` contacts the GitHub Releases API when available and degrades to an unavailable status when offline. `lixet --update` requires network access.

Updates use the installed stable or prerelease channel and accept only a newer GitHub Release with:

- a versioned `lixet-<version>.zip` asset;
- a matching `.sha256` file or `SHA256SUMS` asset;
- a valid SemVer release tag matching the archive's `VERSION` file.

Mutable branch archives, same-version reinstalls, downgrades, symlinks, special files, unsafe paths, oversized archives, and checksum mismatches are rejected. The staged CLI is compiled and smoke-tested before the existing installation is replaced.

## Exit Codes

| Code | Meaning |
| ---: | --- |
| `0` | Completed successfully with no unresolved detected issue |
| `1` | Scan completed, but issues remain or a dry-run found issues |
| `2` | Invalid command-line usage |
| `3` | Inspection or runtime check failed |
| `4` | Repair, verification, installation, or update failed |
| `5` | Rollback failed |

An unavailable or skipped required check never produces a healthy result.

## Known Limitations

- The configured Linux distribution matrix and real symlink paths should be checked in GitHub Actions before each release.
- Service installation and enabled-state discovery varies by distribution; Lixet reports unsupported or unavailable checks instead of guessing.
- SELinux labels, POSIX ACLs, and extended attributes are not yet preserved explicitly.
- Release archives are SHA-256 verified but not signed.
- There is no JSON output, package repository, shell completion, or user-facing backup browser/restore command yet.

See [Architecture](ARCHITECTURE.md) and [Contributing](CONTRIBUTING.md) for project details.

## Support

If Lixet saves you time or helps recover a broken server, you can support the project.

### TON (Gram)

```text
UQANiDCA6hWl7BL0k6iJW9eeJ_BZ207qlrRcK3Fa_K4G_J64
```

## License

Lixet is released under the MIT License. See [LICENSE](LICENSE).
