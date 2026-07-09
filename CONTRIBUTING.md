# Contributing to Lixet

Thank you for considering a contribution to Lixet.

Lixet is a deterministic recovery tool for Linux administrators. Changes should keep the project simple, safe, and easy to understand.

---

# Principles

- Keep the user command simple: `lixet scan <service>` and `lixet doctor`.
- Do not add AI-generated diagnosis or repair logic.
- Prefer the Python standard library.
- Do not modify system files without using the backup flow.
- Keep repairs small, explicit, and explainable.
- Include evidence for reported issues whenever a system command or parser result provides it.
- Keep CLI output clean and useful for both colored terminals and plain logs.
- Report uncertain problems instead of guessing a fix.

---

# Adding a Validator

When adding support for a service:

1. Add inspection logic under `services/`.
2. Add deterministic rules under `validators/`.
3. Return clear issue data: code, severity, description, file path, line number, evidence, source command, and fixes when safe.
4. Use repair actions supported by `repair/manager.py`.
5. Add service registration in `core/engine.py`.
6. Add verifier support when a reliable command exists.

Validators should never write files directly.

---

# Repair Rules

A repair should be added only when:

- The problem is deterministic.
- The expected healthy state is clear.
- The change is small.
- The repair can be previewed.
- The original file is backed up first.
- Verification can run when the service provides a verifier.

If these conditions are not true, report the issue without an automatic fix.

---

# Pull Requests

Before opening a pull request:

1. Keep the change focused.
2. Avoid unrelated refactors.
3. Use clear names for validators, services, and issue codes.
4. Update user-facing documentation when behavior changes.
5. Explain what problem the change solves.

For larger changes, open an issue first so the design can be discussed.

---

# Bug Reports

Good bug reports include:

- The command that was run
- The Linux distribution
- The affected service
- The relevant configuration file
- The exact terminal output
- What you expected Lixet to do

This helps keep fixes deterministic and reproducible.
