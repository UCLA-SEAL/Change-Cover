from pathlib import Path
import subprocess
import docker
from typing import List

from rich.console import Console

from approach.base.pr_patch import PRPatch
from approach.utils.prepare_docker_files import (
    generate_dockerfile,
    build_docker_image
)
from approach.coverage.get_relevance import check_relevance

console = Console(color_system=None)


class IsolatedEnvironment(object):

    def __init__(
            self, pr_patch: PRPatch, abs_custom_dockerfile_path: str = None):
        self.pr_patch = pr_patch
        self.abs_custom_dockerfile_path = abs_custom_dockerfile_path

    def _get_dockerfile(self) -> str:
        if self.abs_custom_dockerfile_path:
            return self.abs_custom_dockerfile_path
        current_file_parent = Path(__file__).parent
        if self.pr_patch.repo_name.lower() == "scipy":
            dockerfile_path = current_file_parent / ".." / ".." / \
                "docker" / "scipy" / "full_test_suite" / "dockerfile"
            return str(dockerfile_path.resolve())
        if self.pr_patch.repo_name.lower() == "qiskit":
            dockerfile_path = current_file_parent / ".." / ".." / \
                "docker" / "qiskit" / "only_python" / "dockerfile"
            return str(dockerfile_path.resolve())
        if self.pr_patch.repo_name.lower() == "pandas":
            dockerfile_path = current_file_parent / ".." / ".." / \
                "docker" / "pandas" / "full_test_suite" / "dockerfile"
            return str(dockerfile_path.resolve())
        if self.pr_patch.repo_name.lower() == "astroquery":
            dockerfile_path = current_file_parent / ".." / ".." / \
                "docker" / "astroquery" / "Dockerfile"
            return str(dockerfile_path.resolve())
        if self.pr_patch.repo_name.lower() == "ax":
            dockerfile_path = current_file_parent / ".." / ".." / \
                "docker" / "ax" / "Dockerfile"
            return str(dockerfile_path.resolve())
        console.log(
            f"No Dockerfile found for the repository: {self.pr_patch.repo_name}")
        return None

    def _prepare_execution_environment(self) -> None:
        dockerfile = self._get_dockerfile()
        if dockerfile:
            uid = subprocess.check_output(['id', '-u']).decode().strip()
            gid = subprocess.check_output(['id', '-g']).decode().strip()
            img_suffix = None
            # I'm not using image suffix, feel free to comment this
            if self.abs_custom_dockerfile_path and \
                    self.pr_patch.repo_name.lower() not in ["qiskit", "pandas", "scipy"]:
                img_suffix = "custom"
            if self.pr_patch.repo_name.lower() in [
                    "qiskit", "pandas", "scipy"]:
                generate_dockerfile(
                    dockerfile=dockerfile,
                    proj=self.pr_patch.repo_name,
                    pr_number=str(self.pr_patch.pr_number),
                    uid=uid,
                    gid=gid,
                    img_suffix=img_suffix
                )
            else:
                build_docker_image(
                    dockerfile=dockerfile,
                    uid=uid,
                    gid=gid,
                    image_name=self._get_image_name()
                )

    def _get_image_name(self) -> str:
        if self.pr_patch.repo_name.lower() in ["qiskit", "pandas", "scipy"]:
            if self.abs_custom_dockerfile_path:
                return f"{self.pr_patch.repo_name}-pr-{self.pr_patch.pr_number}"
            return f"{self.pr_patch.repo_name}-pr-{self.pr_patch.pr_number}"
        else:
            current_username = subprocess.check_output(
                ['whoami']).decode().strip()
            return f"{current_username}_{self.pr_patch.repo_name.lower()}"

    def remove_image(self) -> None:
        """Deletes the image using the image name via docker python API."""
        image_name = self._get_image_name()
        client = docker.from_env()
        try:
            client.images.remove(image_name)
            console.log(f"Removed image: {image_name}")
        except Exception as e:
            console.log(f"Error removing image: {e}")

    def _is_execution_environment_ready(self) -> bool:
        image_name = self._get_image_name()
        result = subprocess.run(
            ["docker", "images", "-q", image_name],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        return bool(result.stdout.strip())

    def _dry_run_execution_environment(self) -> None:
        image_name = self._get_image_name()
        if not self._is_execution_environment_ready():
            console.log(f"Docker image not found: {image_name}.")
            console.log("Preparing the execution environment...")
            self._prepare_execution_environment()
        try:
            command = f"git -C /opt/{self.pr_patch.repo_name} rev-parse HEAD"
            # command = f"-c \"git -C /opt/{self.pr_patch.repo_name} rev-parse HEAD\""
            client = docker.from_env()
            container = client.containers.run(
                image=image_name,
                command=command,
                detach=True,
                remove=False
            )
            # wait for the container to finish
            container.wait()
            # print the output
            console.log(container.logs().decode())
        except Exception as e:
            console.log(f"Error running the container: {e}")
        finally:
            container.stop()
            container.remove()

    def _compute_relevance(
            self, abs_coverage_path: str, abs_output_path: str) -> None:
        self.pr_patch.retrieve_diff_file()
        self.pr_patch.download_all_file_contents()

        check_relevance(
            diff_path=self.pr_patch.diff_path,
            after_dir=self.pr_patch.after_dir,
            coverage_path=abs_coverage_path,
            output_path=abs_output_path,
            verbose=True
        )

    def _copy_from_image(
            self, image_filepath: str, output_folder: str) -> None:
        image_name = self._get_image_name()
        filename = Path(image_filepath).name
        abs_path_output = str(Path(output_folder).resolve())
        command = f"cp {image_filepath} /mnt/{filename}"
        try:
            client = docker.from_env()
            container = client.containers.run(
                image=image_name,
                command=f"/bin/bash -c \"{command}\"",
                volumes={abs_path_output: {'bind': '/mnt', 'mode': 'rw'}},
                remove=True
            )
            console.log(
                f"Copied {filename} to {abs_path_output}")
        except Exception as e:
            console.log(f"Error copying from container: {e}")
        return str(Path(abs_path_output) / filename)

    def _run_commands_in_container(
            self,
            commands: List[str],
            image_name: str,
            output_folder: str) -> None:
        """Start a container and run the series of command in it.

        The container is started as a daemon and the commands are run in it.
        The output of the commands is printed to the console.
        The container and the host are connected via a volume, using the
        output folder as the mount point.
        """
        abs_path_output = str(Path(output_folder).resolve())
        try:
            client = docker.from_env()
            container = client.containers.run(
                image=image_name,
                # useless continually running command
                #  to keep the container alive
                command="/bin/bash -c \"while true; do sleep 1; done\"",
                detach=True,
                remove=True,
                tty=True,
                volumes={abs_path_output: {
                    'bind': '/opt/coverage', 'mode': 'rw'}}
            )
            for command in commands:
                console.log(f"Running command: {command}")
                exec_command = container.exec_run(
                    f"/bin/bash -c \"{command}\"",
                    tty=True
                )
                console.log(exec_command.output.decode())
            container.stop()
            container.remove()
        except Exception as e:
            console.log(f"Error running the container: {e}")
            container.stop()
            container.remove()
            raise e
        finally:
            console.log(f"Container {container.name} stopped and removed.")
            client.close()
            console.log("Docker client closed.")
        # Remove the container
        # container.remove(force=True)
        # client.close()
