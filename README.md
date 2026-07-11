# Lixet

Lixet is a Linux command-line tool for finding and repairing common configuration problems.

It reads known system configuration files, runs local validation commands when they are available, and explains what it found before changing anything. Lixet uses deterministic rules; it does not generate fixes with AI or guess what policy your system should use.

> **Status:** Lixet `v0.2.2-beta` is beta software. Test it on non-critical systems first and review repairs before applying them.

## What Lixet Can Do

- Scan one supported service or run a broader system check.
- Show findings with severity, evidence, affected file, and suggested action.
- Offer automatic repair only when the fix is narrow and deterministic.
- Preview supported repairs with `--dry-run`.
- Back up files before writing to protected configuration paths.
- Re-check the result after a repair and roll back if validation fails.
- Update an installed copy from published GitHub Releases.

Many findings are reported without an automatic fix because the correct action depends on your system policy.

## Installation

Lixet requires Linux and Python 3.10 or newer.

```bash
git clone https://github.com/behdadaliz/Lixet.git
cd Lixet
sudo sh install.sh
```

After installation, the `lixet` command is available system-wide:

```bash
lixet
```

## Basic Usage

```bash
lixet                           # Show help
lixet --help                    # Show help
lixet services                  # List supported services
lixet scan ssh                  # Scan one service
lixet scan nginx                # Scan another supported service
lixet scan ssh --dry-run        # Preview repairs without changing files
sudo lixet scan ssh -y          # Apply supported safe repairs
lixet doctor                    # Scan all supported services
lixet doctor --dry-run          # Preview repairs from doctor
sudo lixet doctor -y            # Apply supported safe repairs from doctor
lixet --no-color scan ssh       # Disable colored output
```

Only `scan` accepts a custom configuration path:

```bash
lixet scan nginx --config /path/to/nginx.conf
```

## Supported Services

`lixet services` prints the live list from the installed version. In this release, Lixet supports:

| Service | What Lixet checks |
| --- | --- |
| `ssh` | OpenSSH server configuration and included files |
| `nginx` | Nginx root configuration and included files |
| `ufw` | UFW state, defaults, and runtime status |
| `dns` | Resolver syntax and local manager state |
| `networking` | `/etc/hosts` and local network state |
| `systemd` | systemd runtime state, units, and drop-ins |
| `sudoers` | sudoers syntax through `visudo` |
| `fstab` | fstab syntax through `findmnt` |
| `sysctl` | sysctl load order and effective overrides |

Aliases are also supported: `sshd` and `openssh` map to `ssh`, `hosts` and `network` map to `networking`, and `firewall` maps to `ufw`.

## How Repairs Work

When Lixet finds repairable issues, it shows the problem and asks what to do. You can choose one repairable issue, choose all repairable issues, or stop without changing anything.

Before writing, Lixet creates a backup and checks that the target file still matches what was inspected. After writing, it scans again and uses external validators when the service requires one, such as `sshd`, `nginx`, `visudo`, `findmnt`, or `systemd` checks.

If a repair cannot be verified, Lixet tries to restore the previous files from the backup made for that repair.

## Repair Levels

- **safe** repairs are small deterministic edits. They can be applied with `-y`.
- **guarded** repairs are more sensitive exact-line edits. They require interactive confirmation.
- **report-only** findings do not have an automatic repair because the correct change cannot be proven.

In the current beta, automatic repair is limited. Lixet can restore missing standard localhost entries in `/etc/hosts`, restore the `localhost` name on the loopback line, and offer some exact-line guarded removals for rejected SSH or sudoers lines. Most other findings are reported for manual review.

## Version And Updates

```bash
lixet --version       # Show installed and latest available GitHub Release
sudo lixet --update   # Update an installed copy
```

The updater follows the installed release channel, downloads the latest compatible GitHub Release source archive, validates the staged source, runs a small CLI self-check, and then installs it transactionally.

## Uninstall

```bash
sudo sh uninstall.sh
```

## Safety

- Scans are read-only.
- Repairs require explicit approval unless `-y` is used for supported safe repairs.
- Guarded repairs are skipped by `-y`.
- Lixet does not restart services for you.
- Lixet does not change firewall rules, mount filesystems, or apply sysctl values directly.
- Normal scans do not require internet access.
- `--version` and `--update` contact GitHub Releases.

## Project Status

Lixet is still early beta. The current focus is predictable diagnostics, conservative repairs, and safe update behavior.

Not available yet: a package repository, shell completions, JSON output, and a user-facing backup restore command.

For more detail, read [ARCHITECTURE.md](ARCHITECTURE.md).

## Contributing

Contributions are welcome, especially small validators, tests, documentation improvements, and careful repair rules. Please read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.

## Support

If Lixet saves you time or helps recover a broken server, you can support the project.

### TON (Gram)

```text
UQANiDCA6hWl7BL0k6iJW9eeJ_BZ207qlrRcK3Fa_K4G_J64
```

## License

Lixet is released under the MIT License. See [LICENSE](LICENSE).
