"""Run the platform launcher and assert its observable exit behavior."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
FALSE_SUCCESS_BANNER = "OpenNotebookLM is starting up"


def write_executable(path: Path, content: str) -> None:
    """Create an executable command double in a controlled temporary directory.

    Args:
        path: File path the launcher will resolve through ``PATH``.
        content: Complete script content to write.

    Returns:
        None.
    """
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def set_jwt(
    env_file: Path,
    value: str = "launcher-test-only-0123456789abcdef",
) -> None:
    """Replace the blank example signing key with a controlled test value.

    Args:
        env_file: Copied environment file to update.
        value: Exact value to put after ``JWT_SECRET_KEY=``.

    Returns:
        None.
    """
    content = env_file.read_text(encoding="utf-8")
    content = content.replace(
        "JWT_SECRET_KEY=",
        f"JWT_SECRET_KEY={value}",
        1,
    )
    env_file.write_text(content, encoding="utf-8")


class LauncherExitTests(unittest.TestCase):
    """Pressure-test blank-secret and Compose-failure launcher branches."""

    def setUp(self) -> None:
        """Create a fresh checkout-shaped directory for one launcher run."""
        self.temporary = tempfile.TemporaryDirectory()
        self.checkout = Path(self.temporary.name)
        self.bin_dir = self.checkout / "bin"
        self.bin_dir.mkdir()
        shutil.copy2(REPO_ROOT / ".env.example", self.checkout / ".env.example")

    def tearDown(self) -> None:
        """Remove the controlled launcher directory."""
        self.temporary.cleanup()

    def run_launcher(self) -> subprocess.CompletedProcess[str]:
        """Run the native launcher with controlled Docker command failures.

        Returns:
            The completed launcher process with captured combined output.
        """
        environment = os.environ.copy()
        environment["PATH"] = str(self.bin_dir) + os.pathsep + environment["PATH"]
        environment["CI"] = "1"

        if os.name == "nt":
            shutil.copy2(REPO_ROOT / "start.bat", self.checkout / "start.bat")
            write_executable(
                self.bin_dir / "docker.cmd",
                """@echo off
:scan
if "%~1"=="" exit /b 0
if "%~1"=="version" exit /b 0
if "%~1"=="config" exit /b 0
if "%~1"=="up" (
  echo synthetic compose failure 1>&2
  exit /b 42
)
shift
goto scan
""",
            )
            write_executable(
                self.bin_dir / "docker-compose.cmd",
                "@echo off\necho synthetic compose failure 1>&2\nexit /b 42\n",
            )
            write_executable(self.bin_dir / "curl.cmd", "@exit /b 1\n")
            write_executable(self.bin_dir / "timeout.cmd", "@exit /b 0\n")
            command = [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", "start.bat"]
        else:
            launcher = self.checkout / "start.sh"
            launcher.write_text(
                (REPO_ROOT / "start.sh").read_text(encoding="utf-8").replace(
                    "\r\n", "\n",
                ),
                encoding="utf-8",
            )
            launcher.chmod(launcher.stat().st_mode | stat.S_IXUSR)
            write_executable(
                self.bin_dir / "docker",
                """#!/bin/sh
for argument in "$@"; do
  [ "$argument" = version ] && exit 0
  [ "$argument" = config ] && exit 0
  if [ "$argument" = up ]; then
    echo 'synthetic compose failure' >&2
    exit 42
  fi
done
exit 0
""",
            )
            write_executable(
                self.bin_dir / "docker-compose",
                "#!/bin/sh\necho 'synthetic compose failure' >&2\nexit 42\n",
            )
            write_executable(self.bin_dir / "curl", "#!/bin/sh\nexit 1\n")
            write_executable(self.bin_dir / "sleep", "#!/bin/sh\nexit 0\n")
            command = ["bash", "start.sh"]

        return subprocess.run(
            command,
            cwd=self.checkout,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            check=False,
        )

    def test_fresh_launcher_rejects_the_copied_blank_jwt(self) -> None:
        """Copying the example may not proceed with its required secret blank."""
        result = self.run_launcher()

        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("JWT_SECRET_KEY", result.stdout)
        self.assertNotIn(FALSE_SUCCESS_BANNER, result.stdout)

    def test_compose_failure_is_the_launcher_failure(self) -> None:
        """A failed Compose up must stop before any startup success banner."""
        env_file = self.checkout / ".env"
        shutil.copy2(REPO_ROOT / ".env.example", env_file)
        set_jwt(env_file)

        result = self.run_launcher()

        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("synthetic compose failure", result.stdout)
        self.assertIn("Compose failed", result.stdout)
        self.assertNotIn(FALSE_SUCCESS_BANNER, result.stdout)

    def test_whitespace_only_jwt_is_rejected_as_blank(self) -> None:
        """Spaces are not a usable signing secret and need the same guidance."""
        env_file = self.checkout / ".env"
        shutil.copy2(REPO_ROOT / ".env.example", env_file)
        set_jwt(env_file, "   ")

        result = self.run_launcher()

        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("JWT_SECRET_KEY", result.stdout)
        self.assertNotIn(FALSE_SUCCESS_BANNER, result.stdout)


if __name__ == "__main__":
    unittest.main()
