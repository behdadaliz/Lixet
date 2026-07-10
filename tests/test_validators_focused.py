# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Focused deterministic validator semantics."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.helpers import row
from validators.dns_validator import DNSValidator
from validators.fstab_validator import FstabValidator
from validators.networking_validator import NetworkingValidator
from validators.ssh_validator import SSHValidator
from validators.sudoers_validator import SudoersValidator
from validators.sysctl_validator import SysctlValidator
from validators.ufw_validator import UFWValidator


class ValidatorTests(unittest.TestCase):
    def test_ssh_accepts_hostname_ipv4_ipv6_and_optional_ports(self) -> None:
        values = ["0.0.0.0", "::", "[::1]:2222", "ssh.example.test:22"]
        rows = [
            {**row(index, f"ListenAddress {value}"), "directive": "ListenAddress", "value": value, "in_match": False}
            for index, value in enumerate(values, start=1)
        ]
        issues = SSHValidator("/tmp/sshd_config").run_rules({"lines": rows, "config_test": {"returncode": 0}})
        self.assertFalse(any(item["code"] == "SSH_INVALID_LISTEN_ADDRESS" for item in issues))

    def test_ssh_hardening_choices_are_report_only(self) -> None:
        rows = [
            {**row(1, "PermitRootLogin yes"), "directive": "PermitRootLogin", "value": "yes", "in_match": False},
            {
                **row(2, "PasswordAuthentication yes"),
                "directive": "PasswordAuthentication",
                "value": "yes",
                "in_match": False,
            },
        ]
        issues = SSHValidator("/tmp/sshd_config").run_rules({"lines": rows, "config_test": {"returncode": 0}})
        self.assertFalse(any(item["repairable"] for item in issues))

    def test_ufw_duplicates_preserve_last_effective_values(self) -> None:
        data = {
            "files": [
                {"role": "state", "file_path": "/tmp/ufw.conf", "lines": [row(1, "ENABLED=no"), row(2, "ENABLED=yes")]},
                {
                    "role": "defaults",
                    "file_path": "/tmp/default-ufw",
                    "lines": [
                        row(1, "IPV6=no"),
                        row(2, "IPV6=yes"),
                        row(3, 'DEFAULT_INPUT_POLICY="ACCEPT"'),
                        row(4, 'DEFAULT_INPUT_POLICY="DROP"'),
                    ],
                },
            ],
            "ufw_status": None,
        }
        issues = UFWValidator().run_rules(data)
        duplicates = [item for item in issues if item["code"].startswith("UFW_DUPLICATE_")]
        self.assertEqual(
            {item["code"] for item in duplicates},
            {"UFW_DUPLICATE_ENABLED", "UFW_DUPLICATE_IPV6", "UFW_DUPLICATE_DEFAULT_INPUT_POLICY"},
        )
        self.assertFalse(any(item["repairable"] for item in duplicates))
        self.assertTrue(all("last assignment is effective" in item["description"] for item in duplicates))

    def test_sysctl_override_evidence_lists_sources_and_effective_value(self) -> None:
        data = {
            "files": [
                {"file_path": "/usr/lib/sysctl.d/10-base.conf", "load_order": 1, "lines": [row(1, "vm.swappiness=60")]},
                {"file_path": "/etc/sysctl.d/90-local.conf", "load_order": 2, "lines": [row(4, "vm.swappiness=10")]},
            ]
        }
        issue = next(item for item in SysctlValidator().run_rules(data) if item["code"] == "SYSCTL_EFFECTIVE_OVERRIDE")
        self.assertIn("previous value '60'", issue["description"])
        self.assertIn("effective value '10'", issue["description"])
        self.assertIn("load 1", issue["evidence"])
        self.assertIn("load 2", issue["evidence"])
        self.assertFalse(issue["repairable"])

    def test_fstab_parses_escaped_whitespace(self) -> None:
        data = {"lines": [row(1, "/dev/sda1 /mnt/my\\040disk ext4 defaults 0 2")], "findmnt_verify": {"returncode": 0}}
        issues = FstabValidator().run_rules(data)
        self.assertFalse(
            any(item["code"] in {"FSTAB_MISSING_FIELDS", "FSTAB_INVALID_NUMERIC_FIELD"} for item in issues)
        )

    def test_dns_never_offers_fallback_resolver(self) -> None:
        issues = DNSValidator().run_rules({"lines": [], "resolver_manager": None, "resolvectl": None})
        self.assertFalse(any(item["repairable"] for item in issues))
        self.assertFalse(any("1.1.1.1" in str(item) for item in issues))

    def test_hosts_invalid_address_is_separate_from_runtime_failure(self) -> None:
        data = {"lines": [row(1, "not-an-ip host")], "ip_route": None, "ip_addr": None, "ip_link": None}
        codes = {item["code"] for item in NetworkingValidator().run_rules(data)}
        self.assertIn("HOSTS_INVALID_ADDRESS", codes)
        self.assertIn("NET_IP_COMMAND_UNAVAILABLE", codes)

    def test_sudoers_main_file_is_never_repaired(self) -> None:
        data = {
            "files": [{"file_path": "/etc/sudoers", "lines": [row(1, "broken", "/etc/sudoers")]}],
            "config_test": {
                "returncode": 1,
                "evidence": "/etc/sudoers:1: syntax error",
                "command": "/usr/sbin/visudo -cf /etc/sudoers",
            },
        }
        issue = SudoersValidator().run_rules(data)[0]
        self.assertFalse(issue["repairable"])

    def test_sudoers_exact_included_line_is_guarded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "sudoers.d"
            directory.mkdir()
            path = directory / "broken"
            path.write_bytes(b"bad rule\n")
            data = {
                "files": [{"file_path": str(path), "lines": [row(1, "bad rule", str(path))]}],
                "config_test": {"returncode": 1, "evidence": f"{path}:1: syntax error", "command": "visudo"},
            }
            issue = SudoersValidator("/etc/sudoers").run_rules(data)[0]
            self.assertTrue(issue["repairable"])
            self.assertEqual(issue["repair_level"], "guarded")
            self.assertEqual(issue["fixes"][0]["expected_original"], "bad rule\n")


if __name__ == "__main__":
    unittest.main()
