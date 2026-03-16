"""INginxReloadGateway — interface + implementations."""
import subprocess


class NginxReloadError(Exception):
    pass


class SubprocessNginxReloadGateway:
    """Calls nginx -s reload via subprocess."""

    def __init__(self, reload_command: str = "nginx -s reload") -> None:
        self._reload_command = reload_command

    def reload(self) -> None:
        try:
            result = subprocess.run(
                self._reload_command.split(),
                capture_output=True,
                timeout=10,
            )
            if result.returncode != 0:
                raise NginxReloadError(result.stderr.decode("utf-8", errors="replace"))
        except FileNotFoundError:
            # nginx not installed in dev — skip
            pass
        except subprocess.TimeoutExpired:
            raise NginxReloadError("nginx reload timed out")


class StubNginxReloadGateway:
    """Test double. Records reload calls."""

    def __init__(self) -> None:
        self.reload_count = 0

    def reload(self) -> None:
        self.reload_count += 1
