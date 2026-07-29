"""NginxConfGenerator — produces cms_routing.conf from active nginx-layer rules."""
import os
import shutil
import tempfile
import subprocess
from typing import List


class NginxConfInvalidError(Exception):
    pass


class NginxConfGenerator:
    """Generates an nginx conf snippet from a list of CmsRoutingRule objects."""

    def generate(self, rules: List, default_slug: str) -> str:
        """Build nginx map/geo blocks from rules. Returns conf string."""
        lines = [
            "# CMS routing rules — managed by vbwd-backend CmsRoutingService",
            "# Do not edit manually. Changes will be overwritten on next rule save.",
            "",
        ]

        ip_rules = [r for r in rules if r.match_type == "ip_range"]
        lang_rules = [r for r in rules if r.match_type == "language"]
        cookie_rules = [r for r in rules if r.match_type == "cookie"]

        # geo block for IP ranges
        if ip_rules:
            lines.append("geo $remote_addr $cms_ip_route {")
            lines.append("    default 0;")
            for r in ip_rules:
                lines.append(f"    {r.match_value} {r.target_slug};")
            lines.append("}")
            lines.append("")

        # map block for Accept-Language
        if lang_rules:
            lines.append("map $http_accept_language $cms_lang_route {")
            lines.append("    default '';")
            for r in lang_rules:
                lang = (r.match_value or "").lower()
                lines.append(f"    ~*^{lang} {r.target_slug};")
            lines.append("}")
            lines.append("")

        # map block for cookie
        if cookie_rules:
            lines.append("map $cookie_vbwd_lang $cms_cookie_route {")
            lines.append("    default '';")
            for r in cookie_rules:
                k, _, v = (r.match_value or "").partition("=")
                if k.strip() == "vbwd_lang":
                    lines.append(f"    {v.strip()} {r.target_slug};")
            lines.append("}")
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def _wrap_for_validation(conf_str: str, scratch_dir: str) -> str:
        """Wrap the snippet in a minimal main config so ``nginx -t`` accepts it.

        Two things are needed to make ``nginx -t`` a meaningful check here:

        1. ``generate()`` emits ``geo``/``map`` blocks, which are http-context
           directives. The snippet is ``include``d inside the real config's
           ``http {}`` block, so on its own it is not a valid main config —
           validating it bare fails with ``"geo" directive is not allowed
           here`` wherever nginx is actually installed.
        2. ``nginx -t`` also *opens* the configured pid and error-log paths.
           The compiled-in defaults live under ``/run`` and ``/var/log``, which
           an unprivileged process cannot write, so the test failed with
           ``open() "/run/nginx.pid" failed (13: Permission denied)`` even
           after reporting ``syntax is ok``. Pointing both at the scratch
           directory keeps the check about the config, not about privileges.
        """
        pid_path = os.path.join(scratch_dir, "nginx-validate.pid")
        log_path = os.path.join(scratch_dir, "nginx-validate.log")
        return (
            f"pid {pid_path};\n"
            f"error_log {log_path};\n"
            f"events {{}}\n"
            f"http {{\n{conf_str}\n}}\n"
        )

    def write_and_validate(self, conf_str: str, path: str) -> None:
        """Write conf to path. Skips nginx -t if nginx is not available."""
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        # Validate the snippet in the context it is included into, not bare.
        scratch_dir = tempfile.mkdtemp(prefix="vbwd-nginx-validate-")
        tmp_path = os.path.join(scratch_dir, "cms_routing_check.conf")
        with open(tmp_path, "w") as handle:
            handle.write(self._wrap_for_validation(conf_str, scratch_dir))
        try:
            result = subprocess.run(
                ["nginx", "-t", "-c", tmp_path],
                capture_output=True,
                timeout=5,
            )
            if result.returncode != 0:
                raise NginxConfInvalidError(
                    f"nginx -t failed: {result.stderr.decode('utf-8', errors='replace')}"
                )
        except FileNotFoundError:
            # nginx not installed in dev — skip validation
            pass
        except subprocess.TimeoutExpired:
            pass
        finally:
            shutil.rmtree(scratch_dir, ignore_errors=True)
        # Write to target
        with open(path, "w") as f:
            f.write(conf_str)
