# Lixet Architecture

Lixet is a deterministic Linux configuration recovery CLI. It inspects known configuration targets, reports evidence-based issues, and applies small reversible repairs only when the repair is safe enough and approved.

The installed user command is:

```bash
lixet
```

---

# Structure

```text
lixet/
|-- backup/       Backup and restore logic
|-- cli/          Command parsing for lixet
|-- core/         Scan, doctor, update, prompt, repair, and verification flow
|-- repair/       Safe line-based file repair operations
|-- services/     File and runtime inspection for supported Linux services
|-- utils/        Shared CLI output helpers
|-- validators/   Deterministic validation rules
|-- install.py    Python installer and uninstaller
|-- install.sh    Simple Linux installer
|-- uninstall.sh  Simple Linux uninstaller
|-- main.py       CLI entry point
|-- manager.py    Compatibility import path
`-- VERSION       Clean semantic version string
```

---

# Command Flow

## `lixet scan ssh`

1. `main.py` starts the CLI.
2. `cli/` parses the command.
3. `core/` selects the requested service.
4. `services/` reads files and runs safe system inspection commands when available.
5. `validators/` return deterministic issue dictionaries.
6. `core/` orders issues by severity: critical, high, medium, low, info.
7. `utils/` prints clean terminal output.
8. If no automatic repair exists, Lixet reports that and does not ask for a repair selection.
9. If a repair is approved, `backup/` creates a backup.
10. `repair/` applies the exact line-based change through an atomic write.
11. `core/` verifies the result when a verifier is available.
12. If verification fails, the backup is restored.

## `lixet doctor`

`doctor` scans all supported services, merges issues, sorts them by severity, and shows a summary. Repairable issues are grouped by repair level. Safe repairs can be applied normally. Guarded repairs require explicit manual confirmation and are skipped by `-y`.

## `lixet --version`

`--version` reads the installed version from `/opt/lixet/VERSION` when running as an installed command. When running from a source checkout, it reads the project root `VERSION` file. It optionally checks GitHub Releases and falls back to tags when release data is unavailable.

Preferred release tag format:

```text
v0.2.0-beta
```

## `lixet --update`

`--update` downloads a GitHub source archive into a temporary directory, extracts it, validates required project files, validates `VERSION`, and only then replaces `/opt/lixet`.

If validation or replacement fails, the previous installation is kept or restored.

---

# Repair Levels

Every issue can declare a repair level:

- `safe`: small deterministic line repair; can run with normal confirmation or `-y`
- `guarded`: sensitive repair; requires explicit interactive confirmation and is skipped by `-y`
- `unsafe`: report-only; never repaired automatically

Guarded repairs are used for changes that can affect SSH access, root/password login, firewall startup, DNS resolver behavior, sudo access, boot mounts, or service startup behavior.

---

# Issue Model

Validators return dictionaries with a consistent shape:

- `id`
- `code`
- `severity`
- `service`
- `description`
- `file_path`
- `line_number`
- `evidence`
- `source_command`
- `safety_note`
- `risk_note`
- `rollback_note`
- `repairable`
- `repair_level`
- `fixes`

Validators never edit files directly.

---

# Repair Actions

`repair/manager.py` supports small line-oriented actions:

- `append`
- `replace`
- `replace_preserve_comment`
- `delete`
- `comment_out`
- `comment_out_with_reason`
- `insert_before`
- `insert_after`

Commenting out is preferred over deleting when preserving user content is safer.

---

# Supported Rule Groups

Lixet currently includes deterministic rules for:

- SSH syntax validation through `sshd -t -f`, port directives, authentication directives, root login warnings, `ListenAddress`, and exact-line guarded repairs for invalid directives
- Nginx syntax validation through `nginx -t -c`, semicolon fixes, worker process value, events block presence, brace diagnostics, and exact-line guarded repairs for invalid directives
- UFW runtime status, inactive firewall reporting, SSH exposure checks, boolean settings, duplicate settings, and default policy validation
- DNS resolver file presence, nameserver validation, duplicate nameservers, resolver command diagnostics, and guarded fallback resolver repair
- Networking default route, non-loopback interface state, non-loopback IP address, and safe `/etc/hosts` localhost recovery
- Systemd degraded state, failed units, unit section validation, `ExecStart`, `Restart`, and `Type`
- sudoers validation through `visudo -cf`
- fstab validation through `findmnt --verify --tab-file`
- sysctl configuration parsing and duplicate key detection

Aliases:

- `hosts` maps to `networking`
- `firewall` maps to `ufw`

---

# Safety Model

Lixet is conservative by design.

- Validators use deterministic rules and real system tools when available.
- Non-repairable issues are shown with evidence but are not offered as automatic fixes.
- Every write is preceded by a backup.
- File writes are performed through a temporary file and atomic replace.
- Unsupported or conflicting repair actions are rejected.
- `-y` only confirms safe repairs.
- Guarded repairs require manual confirmation.
- Service verification runs when a verifier exists.
- Failed verification triggers restore from backup.
- Lixet never restarts SSH, Nginx, UFW, or failed systemd services automatically.
- Lixet never runs `mount -a` or applies sysctl values automatically.

If a safe automatic repair is not clear, Lixet reports the problem without changing the file.

---

# Design Principles

- Keep the CLI simple.
- Prefer the Python standard library.
- Never use AI-generated repairs.
- Avoid broad rewrites.
- Repair only what can be explained.
- Back up before modifying.
- Leave risky cases for the user to review.
