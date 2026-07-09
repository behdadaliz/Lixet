# Contributing to Lixet

Thank you for considering a contribution to Lixet.

Lixet is a deterministic recovery tool for Linux administrators. Changes should keep the project simple, safe, evidence-based, and easy to review.

---

# Principles

- Keep the user command simple: `lixet scan <service>` and `lixet doctor`, with small maintenance flags such as `--version` and `--update`.
- Do not add AI-generated diagnosis or repair logic.
- Prefer the Python standard library.
- Do not modify system files outside the backup and repair flow.
- Keep repairs small, explicit, previewable, and explainable.
- Include evidence whenever a system command, parser, or file inspection provides it.
- Keep CLI output clean in colored terminals and plain logs.
- Report uncertain problems instead of guessing a fix.

---

# Issue Data

Validators should return issue dictionaries with these fields:

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

Repair levels:

- `safe`: small deterministic repairs that can run with normal confirmation or `-y`
- `guarded`: sensitive repairs that require explicit manual confirmation
- `unsafe`: report-only issues with no automatic repair

Use severity carefully:

- `critical`
- `high`
- `medium`
- `low`
- `info`

Syntax failures from real validators such as `sshd -t`, `nginx -t`, `visudo -cf`, or `findmnt --verify` should appear before lower-severity recommendations.

---

# Adding a Validator

When adding support for a service:

1. Add inspection logic under `services/`.
2. Add deterministic rules under `validators/`.
3. Return clear issue data with evidence and source command when available.
4. Declare `repair_level` for every repair.
5. Add `risk_note` for guarded repairs.
6. Use only repair actions supported by `repair/manager.py`.
7. Add service registration in `core/engine.py`.
8. Add verifier support when a reliable command exists.

Validators should never write files directly.

---

# Repair Rules

A repair should be added only when:

- The problem is deterministic.
- The expected healthy state is clear.
- The repair can be previewed.
- The original file is backed up first.
- Verification can run when the service provides a reliable verifier.
- The repair does not restart services or make broad system changes.

Use guarded repairs for changes that could affect access, authentication, firewall behavior, DNS behavior, sudo access, boot mounts, or service startup behavior.

If these conditions are not true, report the issue without an automatic fix.

---

# Pull Requests

Before opening a pull request:

1. Keep the change focused.
2. Avoid unrelated refactors.
3. Use clear names for validators, services, and issue codes.
4. Update user-facing documentation when behavior changes.
5. Explain what problem the change solves and what evidence supports it.

For larger changes, open an issue first so the design can be discussed.

---

# Bug Reports

Good bug reports include:

- The exact command that was run
- The Linux distribution
- The affected service
- The relevant configuration file
- The exact terminal output
- What you expected Lixet to do
- What actually happened

Remove secrets, private keys, tokens, private IPs, and hostnames before posting logs or configuration snippets.
