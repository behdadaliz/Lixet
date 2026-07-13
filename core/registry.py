# GitHub: https://github.com/behdadaliz/Lixet.git | Author: behdadaliz
"""Shared service metadata registry."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Literal

from services.dns_service import DNSService
from services.fail2ban_service import Fail2banService
from services.fstab_service import FstabService
from services.networking_service import NetworkingService
from services.nginx_service import NginxService
from services.ssh_service import SSHService
from services.sudoers_service import SudoersService
from services.sysctl_service import SysctlService
from services.systemd_service import SystemdService
from services.ufw_service import UFWService
from validators.dns_validator import DNSValidator
from validators.fail2ban_validator import Fail2banValidator
from validators.fstab_validator import FstabValidator
from validators.networking_validator import NetworkingValidator
from validators.nginx_validator import NginxValidator
from validators.ssh_validator import SSHValidator
from validators.sudoers_validator import SudoersValidator
from validators.sysctl_validator import SysctlValidator
from validators.systemd_validator import SystemdValidator
from validators.ufw_validator import UFWValidator

TargetType = Literal["file", "directory"]


@dataclass(frozen=True)
class DetectionSignature:
    text: str
    weight: int = 15


@dataclass(frozen=True)
class ServiceSpec:
    name: str
    aliases: tuple[str, ...]
    description: str
    default_path: str
    inspector: type
    validator: type
    discovery_command: str
    absence_allowed: bool
    system_critical: bool
    accepted_target_types: tuple[TargetType, ...]
    known_paths: tuple[str, ...]
    filename_patterns: tuple[str, ...]
    parent_patterns: tuple[str, ...]
    detection_signatures: tuple[DetectionSignature, ...]
    config_only: bool = False

    def engine_spec(self) -> dict[str, Any]:
        return {
            "service": self.inspector,
            "validator": self.validator,
            "default": self.default_path,
            "command": self.discovery_command,
            "required": not self.absence_allowed,
            "config_only": self.config_only,
            "description": self.description,
            "accepted_target_types": self.accepted_target_types,
        }

    def matches_filename(self, name: str) -> bool:
        return any(fnmatch.fnmatchcase(name, pattern) for pattern in self.filename_patterns)

    def matches_parent(self, path: PurePosixPath) -> bool:
        parent = _posix(str(path.parent))
        return any(
            _same_or_suffix(parent, pattern) or fnmatch.fnmatchcase(parent, pattern)
            for pattern in self.parent_patterns
        )


_SERVICES: tuple[ServiceSpec, ...] = (
    ServiceSpec(
        name="ssh",
        aliases=("sshd", "openssh"),
        description="OpenSSH server configuration and includes",
        default_path="/etc/ssh/sshd_config",
        inspector=SSHService,
        validator=SSHValidator,
        discovery_command="sshd",
        absence_allowed=True,
        system_critical=True,
        accepted_target_types=("file",),
        known_paths=("/etc/ssh/sshd_config",),
        filename_patterns=("sshd_config",),
        parent_patterns=("/etc/ssh", "/etc/ssh/sshd_config.d"),
        detection_signatures=(
            DetectionSignature("permitrootlogin"),
            DetectionSignature("passwordauthentication"),
            DetectionSignature("match user"),
            DetectionSignature("authorizedkeysfile"),
        ),
    ),
    ServiceSpec(
        name="nginx",
        aliases=(),
        description="Nginx root configuration and includes",
        default_path="/etc/nginx/nginx.conf",
        inspector=NginxService,
        validator=NginxValidator,
        discovery_command="nginx",
        absence_allowed=True,
        system_critical=False,
        accepted_target_types=("file",),
        known_paths=("/etc/nginx/nginx.conf",),
        filename_patterns=("nginx.conf",),
        parent_patterns=("/etc/nginx", "/etc/nginx/conf.d", "/etc/nginx/sites-available", "/etc/nginx/sites-enabled"),
        detection_signatures=(DetectionSignature("events {"), DetectionSignature("http {"), DetectionSignature("server {")),
    ),
    ServiceSpec(
        name="ufw",
        aliases=("firewall",),
        description="UFW state, defaults, and runtime status",
        default_path="/etc/ufw/ufw.conf",
        inspector=UFWService,
        validator=UFWValidator,
        discovery_command="ufw",
        absence_allowed=True,
        system_critical=True,
        accepted_target_types=("file",),
        known_paths=("/etc/ufw/ufw.conf", "/etc/default/ufw"),
        filename_patterns=("ufw.conf", "ufw"),
        parent_patterns=("/etc/ufw", "/etc/default"),
        detection_signatures=(
            DetectionSignature("enabled=", 20),
            DetectionSignature("default_input_policy"),
            DetectionSignature("ipv6="),
        ),
    ),
    ServiceSpec(
        name="dns",
        aliases=(),
        description="Resolver syntax and local manager state",
        default_path="/etc/resolv.conf",
        inspector=DNSService,
        validator=DNSValidator,
        discovery_command="resolvectl",
        absence_allowed=False,
        system_critical=True,
        accepted_target_types=("file",),
        known_paths=("/etc/resolv.conf",),
        filename_patterns=("resolv.conf",),
        parent_patterns=("/etc", "/run/systemd/resolve"),
        detection_signatures=(
            DetectionSignature("nameserver", 20),
            DetectionSignature("search "),
            DetectionSignature("domain "),
        ),
        config_only=True,
    ),
    ServiceSpec(
        name="networking",
        aliases=("network", "hosts"),
        description="Hosts file and local network state",
        default_path="/etc/hosts",
        inspector=NetworkingService,
        validator=NetworkingValidator,
        discovery_command="ip",
        absence_allowed=False,
        system_critical=True,
        accepted_target_types=("file",),
        known_paths=("/etc/hosts",),
        filename_patterns=("hosts",),
        parent_patterns=("/etc",),
        detection_signatures=(DetectionSignature("localhost", 20), DetectionSignature("ip6-localhost")),
        config_only=True,
    ),
    ServiceSpec(
        name="fail2ban",
        aliases=("f2b", "fail2ban-client"),
        description="Fail2ban configuration, includes, jails, and runtime status",
        default_path="/etc/fail2ban",
        inspector=Fail2banService,
        validator=Fail2banValidator,
        discovery_command="fail2ban-client",
        absence_allowed=True,
        system_critical=True,
        accepted_target_types=("file", "directory"),
        known_paths=("/etc/fail2ban", "/etc/fail2ban/jail.conf", "/etc/fail2ban/jail.local", "/etc/fail2ban/fail2ban.conf", "/etc/fail2ban/fail2ban.local"),
        filename_patterns=("fail2ban.conf", "fail2ban.local", "jail.conf", "jail.local"),
        parent_patterns=("/etc/fail2ban", "/etc/fail2ban/jail.d", "/etc/fail2ban/filter.d", "/etc/fail2ban/action.d"),
        detection_signatures=(
            DetectionSignature("[includes]", 25),
            DetectionSignature("[default]", 15),
            DetectionSignature("bantime", 15),
            DetectionSignature("maxretry", 15),
            DetectionSignature("failregex", 15),
        ),
    ),
    ServiceSpec(
        name="systemd",
        aliases=(),
        description="systemd runtime, units, and drop-ins",
        default_path="/etc/systemd/system",
        inspector=SystemdService,
        validator=SystemdValidator,
        discovery_command="systemctl",
        absence_allowed=True,
        system_critical=True,
        accepted_target_types=("file", "directory"),
        known_paths=("/etc/systemd/system",),
        filename_patterns=("*.service", "*.socket", "*.timer"),
        parent_patterns=("/etc/systemd/system", "/etc/systemd/system/*.d", "/usr/lib/systemd/system", "/lib/systemd/system"),
        detection_signatures=(DetectionSignature("[service]"), DetectionSignature("execstart="), DetectionSignature("[unit]")),
    ),
    ServiceSpec(
        name="sudoers",
        aliases=(),
        description="sudoers syntax through visudo",
        default_path="/etc/sudoers",
        inspector=SudoersService,
        validator=SudoersValidator,
        discovery_command="visudo",
        absence_allowed=True,
        system_critical=True,
        accepted_target_types=("file",),
        known_paths=("/etc/sudoers",),
        filename_patterns=("sudoers",),
        parent_patterns=("/etc", "/etc/sudoers.d"),
        detection_signatures=(DetectionSignature("all=(all"), DetectionSignature("includedir"), DetectionSignature("sudoers")),
    ),
    ServiceSpec(
        name="fstab",
        aliases=(),
        description="fstab syntax through findmnt",
        default_path="/etc/fstab",
        inspector=FstabService,
        validator=FstabValidator,
        discovery_command="findmnt",
        absence_allowed=True,
        system_critical=True,
        accepted_target_types=("file",),
        known_paths=("/etc/fstab",),
        filename_patterns=("fstab",),
        parent_patterns=("/etc",),
        detection_signatures=(DetectionSignature("defaults 0"), DetectionSignature("x-systemd.")),
        config_only=True,
    ),
    ServiceSpec(
        name="sysctl",
        aliases=(),
        description="sysctl load order and effective overrides",
        default_path="/etc/sysctl.conf",
        inspector=SysctlService,
        validator=SysctlValidator,
        discovery_command="sysctl",
        absence_allowed=True,
        system_critical=True,
        accepted_target_types=("file",),
        known_paths=("/etc/sysctl.conf",),
        filename_patterns=("sysctl.conf",),
        parent_patterns=("/etc/sysctl.d", "/run/sysctl.d", "/usr/local/lib/sysctl.d", "/usr/lib/sysctl.d", "/lib/sysctl.d"),
        detection_signatures=(DetectionSignature("net.ipv4."), DetectionSignature("vm."), DetectionSignature("kernel.")),
        config_only=True,
    ),
)

_BY_NAME = {item.name: item for item in _SERVICES}
_ALIASES = {alias: item.name for item in _SERVICES for alias in item.aliases}


def iter_services() -> tuple[ServiceSpec, ...]:
    return _SERVICES


def service_names() -> tuple[str, ...]:
    return tuple(item.name for item in _SERVICES)


def get_service(name: str) -> ServiceSpec:
    return _BY_NAME[name]


def resolve_service_name(name: str) -> str:
    key = name.lower()
    return _ALIASES.get(key, key)


def aliases() -> dict[str, str]:
    return dict(_ALIASES)


def aliases_for(service: str) -> tuple[str, ...]:
    return get_service(resolve_service_name(service)).aliases


def valid_target_types() -> tuple[str, ...]:
    found: list[str] = []
    for spec in _SERVICES:
        for item in spec.accepted_target_types:
            if item not in found:
                found.append(item)
    return tuple(found)


def service_help() -> tuple[tuple[str, str], ...]:
    return tuple((item.name, item.description) for item in _SERVICES)


def _posix(path: str) -> str:
    return PurePosixPath(path.replace("\\", "/")).as_posix()


def _same_or_suffix(path: str, known: str) -> bool:
    clean = PurePosixPath(path).as_posix().rstrip("/")
    target = PurePosixPath(known).as_posix().rstrip("/")
    return clean == target or clean.endswith(target)
