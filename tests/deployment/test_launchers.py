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

    def run_launcher(
        self,
        profile: str | None = None,
        required_wait_timeout: int | None = None,
        compose_up_subcommand: str = "up",
    ) -> subprocess.CompletedProcess[str]:
        """Run the native launcher with controlled Docker command failures.

        Args:
            profile: Optional launcher profile supplied as one quoted argument.
            required_wait_timeout: Exact wait budget required by the Docker double.
            compose_up_subcommand: Subcommand substituted for `up` in the test copy.

        Returns:
            The completed launcher process with captured combined output.
        """
        environment = os.environ.copy()
        environment["PATH"] = str(self.bin_dir) + os.pathsep + environment["PATH"]
        environment["CI"] = "1"

        if os.name == "nt":
            launcher = self.checkout / "start.bat"
            shutil.copy2(REPO_ROOT / "start.bat", launcher)
            if compose_up_subcommand != "up":
                launcher_source = launcher.read_text(encoding="utf-8")
                expected_command = " up -d --build --wait "
                assert launcher_source.count(expected_command) == 1
                launcher.write_text(
                    launcher_source.replace(
                        expected_command,
                        f" {compose_up_subcommand} -d --build --wait ",
                    ),
                    encoding="utf-8",
                )
            if required_wait_timeout is None:
                docker_double = """@echo off
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
"""
            else:
                docker_double = f"""@echo off
setlocal EnableExtensions EnableDelayedExpansion
set "PREVIOUS="
set "SAW_UP="
set "SAW_TIMEOUT="
set "SAW_METADATA="
:scan
if "%~1"=="" goto evaluate
if "%~1"=="version" set "SAW_METADATA=1"
if "%~1"=="config" set "SAW_METADATA=1"
if "%~1"=="up" set "SAW_UP=1"
if "!PREVIOUS!"=="--wait-timeout" (
  if "%~1"=="{required_wait_timeout}" (
    set "SAW_TIMEOUT=1"
  ) else (
    exit /b 86
  )
)
set "PREVIOUS=%~1"
shift
goto scan
:evaluate
if defined SAW_UP (
  if defined SAW_TIMEOUT exit /b 0
  exit /b 86
)
if defined SAW_TIMEOUT exit /b 86
if defined SAW_METADATA exit /b 0
exit /b 86
"""
            write_executable(self.bin_dir / "docker.cmd", docker_double)
            write_executable(
                self.bin_dir / "docker-compose.cmd",
                "@echo off\necho synthetic compose failure 1>&2\nexit /b 42\n",
            )
            write_executable(self.bin_dir / "curl.cmd", "@exit /b 1\n")
            write_executable(self.bin_dir / "timeout.cmd", "@exit /b 0\n")
            command = [
                os.environ.get("COMSPEC", "cmd.exe"),
                "/d",
                "/c",
                "start.bat",
            ]
            if profile is not None:
                write_executable(
                    self.checkout / "invoke-launcher.cmd",
                    f'@call start.bat "{profile}"\n@exit /b %ERRORLEVEL%\n',
                )
                command[-1] = "invoke-launcher.cmd"
        else:
            launcher = self.checkout / "start.sh"
            shutil.copy2(REPO_ROOT / "start.sh", launcher)
            if compose_up_subcommand != "up":
                launcher_source = launcher.read_text(encoding="utf-8")
                expected_command = " up -d --build --wait "
                assert launcher_source.count(expected_command) == 1
                launcher.write_text(
                    launcher_source.replace(
                        expected_command,
                        f" {compose_up_subcommand} -d --build --wait ",
                    ),
                    encoding="utf-8",
                )
            if required_wait_timeout is None:
                docker_double = """#!/bin/sh
for argument in "$@"; do
  [ "$argument" = version ] && exit 0
  [ "$argument" = config ] && exit 0
  if [ "$argument" = up ]; then
    echo 'synthetic compose failure' >&2
    exit 42
  fi
done
exit 0
"""
            else:
                docker_double = f"""#!/bin/sh
previous=''
saw_up=0
saw_timeout=0
saw_metadata=0
for argument in "$@"; do
  [ "$argument" = version ] && saw_metadata=1
  [ "$argument" = config ] && saw_metadata=1
  [ "$argument" = up ] && saw_up=1
  if [ "$previous" = --wait-timeout ]; then
    [ "$argument" = {required_wait_timeout} ] || exit 86
    saw_timeout=1
  fi
  previous="$argument"
done
[ "$saw_up" -eq 1 ] && [ "$saw_timeout" -eq 1 ] && exit 0
[ "$saw_timeout" -eq 1 ] && exit 86
[ "$saw_metadata" -eq 1 ] && exit 0
exit 86
"""
            write_executable(self.bin_dir / "docker", docker_double)
            write_executable(
                self.bin_dir / "docker-compose",
                "#!/bin/sh\necho 'synthetic compose failure' >&2\nexit 42\n",
            )
            write_executable(self.bin_dir / "curl", "#!/bin/sh\nexit 1\n")
            write_executable(self.bin_dir / "sleep", "#!/bin/sh\nexit 0\n")
            command = [str(launcher)]
            if profile is not None:
                command.append(profile)

        try:
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
        except PermissionError as error:
            return subprocess.CompletedProcess(
                command,
                126,
                stdout=f"Direct launcher execution failed: {error}\n",
            )

    @unittest.skipIf(os.name == "nt", "Linux executable-bit contract")
    def test_fresh_linux_checkout_executes_launcher_directly(self) -> None:
        """The advertised ``./start.sh`` invocation must reach the launcher."""
        result = self.run_launcher()

        self.assertNotEqual(result.returncode, 126, result.stdout)
        self.assertIn("JWT_SECRET_KEY", result.stdout)

    @unittest.skipUnless(os.name == "nt", "Windows CMD parsing contract")
    def test_unknown_profile_metacharacters_cannot_execute_commands(self) -> None:
        """An unknown quoted profile must not become a second CMD command."""
        env_file = self.checkout / ".env"
        shutil.copy2(REPO_ROOT / ".env.example", env_file)
        set_jwt(env_file)
        marker = self.checkout / "issue53-profile-injected.txt"
        profile = f"unknown&echo injected>{marker.name}&rem"

        result = self.run_launcher(profile)

        self.assertFalse(marker.exists(), result.stdout)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("ERROR: Unknown profile. Use", result.stdout)

    def test_launcher_waits_through_the_cold_model_startup_budget(self) -> None:
        """A healthy cold start may take the full production wait budget."""
        env_file = self.checkout / ".env"
        shutil.copy2(REPO_ROOT / ".env.example", env_file)
        set_jwt(env_file)

        result = self.run_launcher(required_wait_timeout=900)

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn(FALSE_SUCCESS_BANNER, result.stdout)

    def test_wait_budget_requires_the_compose_up_subcommand(self) -> None:
        """A timeout on a different Compose command may not satisfy the double."""
        env_file = self.checkout / ".env"
        shutil.copy2(REPO_ROOT / ".env.example", env_file)
        set_jwt(env_file)

        result = self.run_launcher(
            required_wait_timeout=900,
            compose_up_subcommand="ps",
        )

        self.assertEqual(result.returncode, 86, result.stdout)
        self.assertNotIn(FALSE_SUCCESS_BANNER, result.stdout)

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
