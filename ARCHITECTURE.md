# Lixet Architecture

Lixet is a deterministic Linux recovery CLI. Its job is simple: inspect known configuration files, detect safe and well-defined problems, explain them, and apply small repairs only after approval.

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
|-- services/     File inspection for supported Linux services
|-- utils/        Shared CLI output helpers
|-- validators/   Deterministic validation rules
|-- install.py    Python installer and uninstaller
|-- install.sh    Simple Linux installer
|-- uninstall.sh  Simple Linux uninstaller
|-- main.py       CLI entry point
|-- manager.py    Compatibility import path
`-- VERSION       Installed version or release name
```

---

# Flow

## `lixet scan ssh`

1. `main.py` starts the CLI.
2. `cli/` parses the command.
3. `core/` selects the requested service.
4. `services/` reads the target configuration.
5. `validators/` returns deterministic issues and proposed repairs.
6. `core/` orders issues by severity and shows clean CLI output.
7. If approved, `backup/` creates a backup.
8. `repair/` applies the exact line-based change.
9. `core/` verifies the result when a verifier is available.
10. If verification fails, the backup is restored.

## `lixet doctor`

`doctor` scans all supported services and lists detected issues. The user can choose one issue, all repairable issues, or skip repair.

## `lixet --update`

`--update` downloads the latest GitHub source archive and updates the installed `/opt/lixet` version. If replacement fails, the previous installed version is restored.

## `lixet --version`

`--version` reads the installed version from the local `VERSION` file, then checks GitHub Releases for the latest published version name. If no release exists, it falls back to GitHub tags.

---

# Safety Model

Lixet is conservative by design.

- Validators never edit files directly.
- Validators use real system tools such as `sshd -t` and `nginx -t` when available.
- Issues are ordered globally by severity: critical, high, medium, low, info.
- Non-repairable issues are shown with evidence but are not offered as automatic fixes.
- Repairs are explicit actions such as `replace`, `delete`, `append`, or `insert_before`.
- Every write is preceded by a backup.
- File writes are performed through a temporary file and atomic replace.
- Unsupported or conflicting repair actions are rejected.
- Service verification runs when a verifier exists.
- Failed verification triggers restore from backup.

If a safe automatic repair is not clear, Lixet reports the problem without changing the file.

---

# Supported Rule Groups

Lixet currently includes deterministic rules for:

- SSH global port, authentication values, `ListenAddress`, and `Match`-aware parsing
- Nginx brace balance, known semicolon repairs, worker process value, and `events` block presence
- UFW boolean settings and default policy validation
- DNS resolver nameserver validation
- Hosts file localhost recovery
- Systemd unit section, `ExecStart`, `Restart`, and `Type` validation
- Runtime diagnostics for systemd, DNS, UFW, and basic networking when safe commands are available

---

# Design Principles

- Keep the CLI simple.
- Prefer the Python standard library.
- Never use AI-generated repairs.
- Avoid broad rewrites.
- Repair only what can be explained.
- Back up before modifying.
- Leave risky cases for the user to review.
