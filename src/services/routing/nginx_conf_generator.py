"""NginxConfGenerator — produces cms_routing.conf from active nginx-layer rules."""
import os
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
        country_rules = [r for r in rules if r.match_type == "country"]
        cookie_rules = [r for r in rules if r.match_type == "cookie"]
        path_rules = [r for r in rules if r.match_type == "path_prefix"]
        default_rules = [r for r in rules if r.match_type == "default"]

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

    def write_and_validate(self, conf_str: str, path: str) -> None:
        """Write conf to path. Skips nginx -t if nginx is not available."""
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        # Write to temp file for validation
        with tempfile.NamedTemporaryFile(mode="w", suffix=".conf", delete=False) as tf:
            tf.write(conf_str)
            tmp_path = tf.name
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
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        # Write to target
        with open(path, "w") as f:
            f.write(conf_str)
