"""
docker_utils.py

Utility functions for managing Docker containers using the Docker SDK for Python.
Provides modular functions for starting containers, executing commands,
processing output, and cleaning up.
"""

import docker
import time
import io
import tarfile
from rich.console import Console
from rich.table import Table
from typing import List
from concurrent.futures import ThreadPoolExecutor, TimeoutError


docker_client = docker.from_env()
console = Console(color_system=None)


def parse_volume_mappings(volume_list):
    """
    Parse a list of volume strings into a dictionary for docker-py volume mounts.

    Each volume string should be in the format:
        "host_path:container_path[:mode]"

    Example:
        - "/home/user/data:/app/data"
        - "/home/user/logs:/app/logs:ro"

    Args:
        volume_list (list[str]): A list of volume mapping strings.

    Returns:
        dict: A dictionary mapping host paths to {'bind': container_path, 'mode': mode}.
    """
    volumes = {}
    for volume_str in volume_list:
        parts = volume_str.split(":")
        if len(parts) == 2:
            host_path, container_path = parts
            mode = "rw"
        elif len(parts) == 3:
            host_path, container_path, mode = parts
        else:
            raise ValueError(
                f"Volume argument '{volume_str}' must be in the format "
                "host_path:container_path[:mode]"
            )
        volumes[host_path] = {
            "bind": container_path,
            "mode": mode
        }
    return volumes


def start_container(image_name: str, volumes_dict: dict = None):
    """
    Start a new container from a specified Docker image, optionally mounting volumes.

    Args:
        image_name (str): The name of the Docker image (e.g. 'python:3.10-slim').
        volumes_dict (dict, optional): A dictionary of volume mappings, where keys are
            host paths and values are {'bind': container_path, 'mode': mode}.
            Defaults to None, meaning no volumes are mounted.

    Returns:
        docker.models.containers.Container: The started container object.

    Raises:
        docker.errors.ImageNotFound: If the specified image is not found locally.
        docker.errors.APIError: If there's an error communicating with the Docker API.
    """
    try:
        console.print(
            f"Starting container from image: {image_name}", style="bold blue")
        container = docker_client.containers.run(
            image=image_name,
            detach=True,
            stdin_open=True,
            tty=True,
            volumes=volumes_dict or {},
        )
        console.print(
            f"Container started: {container.short_id}", style="bold green")
        return container
    except docker.errors.ImageNotFound:
        console.print(
            f"Error: Image '{image_name}' not found.", style="bold red")
        raise
    except docker.errors.APIError as e:
        console.print(f"Error: Docker API error: {e}", style="bold red")
        raise


def execute_command(
        container, command: List[str],
        suppress: bool = False, workdir: str = None, env: dict = None):
    """
    Execute a command inside a running Docker container.

    Args:
        container (docker.models.containers.Container): The container object in which to run the command.
        command (List[str]): The command to execute (e.g. ['ls', '/'], ['python', '--version']).
        suppress (bool, optional): If True, do not raise a RuntimeError on non-zero exit code;
            instead return stderr. Defaults to False.
        workdir (str, optional): The working directory inside the container to execute the command. Defaults to None.
        env (dict/list, optional): Environment variables to set in the container. Defaults to None.
            A dictionary or a list of strings in the following format ["PASSWORD=xxx"] or {"PASSWORD": "xxx"}.

    Returns:
        str:
            - On success (exit_code=0), the standard output from the command.
            - If suppress=True and exit_code!=0, returns the stderr string instead of raising an error.

    Raises:
        RuntimeError: If suppress=False and the command returns a non-zero exit code.
        docker.errors.APIError: If there's an error communicating with the Docker API.
        Exception: For any other unexpected errors.
    """
    try:
        console.print(
            f"Executing command in container {container.short_id}: {command}",
            style="bold blue"
        )
        start_time = time.time()
        exit_code, output = container.exec_run(
            command, demux=True, stdin=True, workdir=workdir, environment=env)

        stdout = output[0].decode() if output[0] else ""
        stderr = output[1].decode() if output[1] else ""

        # Handle non-zero exit
        if exit_code == 124:
            elapsed_time = time.time() - start_time
            console.print(
                f"Command {command} timed out after real {elapsed_time:.2f} seconds.",
                style="bold red")
            raise RuntimeError(
                f"Command '{command}' timed out after {elapsed_time} seconds.")
        if exit_code != 0:
            console.print(
                f"Command failed: {stderr}, exit code {exit_code}",
                style="bold red")
            if suppress:
                # Silently return stderr (no exception raised)
                return stdout + stderr
            else:
                raise RuntimeError(
                    f"Command '{command}' failed with exit code {exit_code}:\n {stdout + stderr}"
                )

        return stdout

    except docker.errors.APIError as e:
        console.print(f"Error: Docker API error: {e}", style="bold red")
        raise
    except Exception as e:
        console.print(f"Error: {e}", style="bold red")
        raise


def read_from_container_file(container, file_path: str):
    """
    Read the contents of a file from a running Docker container.

    Args:
        container (docker.models.containers.Container): The container object from which to read the file.
        file_path (str): The path to the file inside the container.

    Returns:
        str: The contents of the file.

    Raises:
        RuntimeError: If the command fails or if the file is not found.
        docker.errors.APIError: If there's an error communicating with the Docker API.
        Exception: For any other unexpected errors.
    """
    try:
        # console.print(f"Reading file from container {container.short_id}: {file_path}", style="bold blue")
        stream, stat = container.get_archive(file_path)
        buffer = io.BytesIO(b"".join(stream))

        with tarfile.open(fileobj=buffer) as tf:
            member = tf.getmembers()[0]                    # only one file
            content = tf.extractfile(member).read().decode()
        return content

    except docker.errors.APIError as e:
        console.print(f"Error: Docker API error: {e}", style="bold red")
        raise
    except RuntimeError as e:
        console.print(f"Error: {e}", style="bold red")
        raise
    except Exception as e:
        console.print(f"Error: {e}", style="bold red")
        raise


def write_to_container_file(container, file_path: str, content: str):
    """
    Write content to a file inside a running Docker container.

    Args:
        container (docker.models.containers.Container): The container object in which to write the file.
        file_path (str): The path to the file inside the container.
        content (str): The content to write to the file.

    Returns:
        None

    Raises:
        RuntimeError: If the command fails or if the file is not found.
        docker.errors.APIError: If there's an error communicating with the Docker API.
        Exception: For any other unexpected errors.
    """
    try:
        # console.print(f"Writing to file in container {container.short_id}: {file_path}", style="bold blue")
        tar_stream = io.BytesIO()
        with tarfile.open(fileobj=tar_stream, mode="w") as tar:
            # Encode the content first to get the correct byte representation
            # and length
            encoded_content = content.encode('utf-8')  # Explicitly use utf-8

            info = tarfile.TarInfo(name=file_path)
            info.size = len(encoded_content)
            tar.addfile(tarinfo=info, fileobj=io.BytesIO(encoded_content))

        tar_stream.seek(0)
        container.put_archive(path="/", data=tar_stream)

    except docker.errors.APIError as e:
        console.print(f"Error: Docker API error: {e}", style="bold red")
        raise
    except Exception as e:
        console.print(f"Error: {e}", style="bold red")
        raise


def clean_up_container(container):
    """
    Stop and remove a Docker container.

    Args:
        container (docker.models.containers.Container): The container object to be cleaned up.

    Returns:
        None

    Raises:
        docker.errors.APIError: If there's an error communicating with the Docker API.
        Exception: For any other unexpected errors.
    """
    try:
        console.print(
            f"Stopping and removing container: {container.short_id}",
            style="bold blue"
        )
        container.stop()
        container.remove()
        console.print(
            f"Container {container.short_id} removed.", style="bold green")
    except docker.errors.APIError as e:
        console.print(f"Error: Docker API error: {e}", style="bold red")
        raise
    except Exception as e:
        console.print(f"Error: {e}", style="bold red")
        raise
