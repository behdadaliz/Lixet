# Lixet

Lixet is a deterministic Linux configuration recovery CLI.

It checks common Linux configuration problems, explains what it found, and offers small repairs only when the fix is clear. It is not an AI tool, it does not guess, and it does not rewrite full configuration files.

Lixet is currently beta software. Review every repair before using it on important systems.

---

# Installation

```bash
git clone https://github.com/behdadaliz/Lixet.git
cd Lixet
sudo sh install.sh
```

After installation, the command is available as:

```bash
lixet
```

To uninstall:

```bash
sudo sh uninstall.sh
```

---

# Basic Usage

Show help:

```bash
lixet
lixet --help
```

Show the installed version and the latest GitHub release when available:

```bash
lixet --version
```

Update the installed version:

```bash
sudo lixet --update
```

Show supported services:

```bash
lixet services
```

Scan one service:

```bash
lixet scan ssh
lixet scan nginx
lixet scan sudoers
lixet scan fstab
lixet scan sysctl
```

Scan all supported services:

```bash
lixet doctor
```

Preview repairs without changing files:

```bash
lixet scan ssh --dry-run
lixet doctor --dry-run
```

Apply safe repairs without prompting:

```bash
lixet scan ssh -y
lixet doctor -y
```

Disable colored output:

```bash
lixet --no-color scan ssh
```

---

# Supported Services

Run this command to see the same list in your terminal with short descriptions:

```bash
lixet services
```

Lixet currently checks:

- SSH
- Nginx
- UFW
- DNS resolver configuration
- Networking and `/etc/hosts`
- Systemd service units
- sudoers
- fstab
- sysctl configuration

Aliases:

- `lixet scan hosts` maps to `networking`
- `lixet scan firewall` maps to `ufw`

---

# Repair Policy

Every issue has a repair level:

- `safe`: small deterministic file repairs that can run with normal confirmation or `-y`
- `guarded`: sensitive repairs that require explicit interactive confirmation and are skipped by `-y`
- `unsafe`: report-only issues with no automatic repair

Lixet uses guarded repairs for changes that could affect remote access, authentication, firewall behavior, boot mounts, sudo access, or service startup behavior.

If Lixet cannot prove that a repair is safe enough, it reports the issue and leaves the system unchanged.

---

# How Repairs Work

When Lixet finds issues, it shows the problem, location, evidence when available, source command when available, repair level, and planned change.

If you approve a repair, Lixet:

1. Shows the planned file change.
2. Creates a backup before writing.
3. Applies a small line-based edit.
4. Runs a verifier when the service has one available.
5. Restores the backup if verification fails.

`-y` applies only safe repairs. Guarded repairs are skipped with an explanation.

---

# Safety Model

Lixet is intentionally conservative.

- No AI-generated repairs
- No guessing
- No hidden edits
- No full-file rewrites
- No repair without a backup
- No automatic service restarts
- No automatic firewall rule deletion
- No automatic mount or sysctl apply
- No automatic repair when the safe change is unclear

The goal is not to replace an administrator. The goal is to make common configuration problems easier to see and safer to fix.

---

# Requirements

- Linux
- Python 3.10+
- Root or sudo privileges for repairing system configuration files
- Relevant system tools for deeper checks, such as `sshd`, `nginx`, `ufw`, `ip`, `systemctl`, `visudo`, or `findmnt`

---

# Project Status

Lixet is in beta. This release focuses on stronger diagnostics, repair safety levels, more supported services, guarded repairs for sensitive changes, and cleaner CLI output.

---

# Support

If Lixet saves you time or helps recover a broken server, you can support the project.

### TON (Gram)

```text
UQANiDCA6hWl7BL0k6iJW9eeJ_BZ207qlrRcK3Fa_K4G_J64
```

---

# License

Lixet is released under the MIT License.

See the `LICENSE` file for details.
