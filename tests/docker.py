"""Docker availability for tests that start containers."""

import shutil
import subprocess


def docker_available() -> bool:
    """Tell whether a Docker daemon answers.

    Returns:
        ``True`` when ``docker info`` succeeds.
    """
    docker = shutil.which("docker")
    if docker is None:
        return False
    result = subprocess.run(  # noqa: S603 - fixed arguments
        [docker, "info"], capture_output=True, check=False
    )
    return result.returncode == 0
