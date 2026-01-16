# test_docker_utils.py
# To run the test, use the following command:
# python -m pytest approach/docker_handling/test_docker_utils.py -v
# If you want to see outputs from the Docker container, add the `-s` flag after pytest

import pytest
from docker.errors import APIError, NotFound
import docker
import os
import time
from approach.docker_handling.docker_utils import (
    start_container,
    clean_up_container,
    execute_command
)


def is_docker_image_available(image_name: str) -> bool:
    try:
        client = docker.from_env()
        images = client.images.list()
        return any(image_name in tag for img in images for tag in img.tags)
    except Exception:
        return False  # In case Docker is not running or any other issue occurs

# @pytest.mark.parametrize("pr_number", ["60628"])
# def test_run_container_like_manual_command(pr_number):
#     """
#     This test replicates the manual Docker run command:
#       docker run --rm -it \
#         -v $(pwd)/data/test_augmentation/002_pandas/pr/test_cases:/workspace/test \
#         -v $(pwd)/data/test_augmentation/002_pandas/pr/diffs:/workspace/diffs \
#         -v $(pwd)/docker/pandas/util:/workspace/util \
#         pandas-pr-${PR_NUMBER} \
#         /bin/bash

#     Then, inside the container, we do:
#         echo $PR_NUMBER
#         echo $PWD

#     And also run:
#         pytest --cov=pandas --cov-report=xml test/*.py
#     """

#     image_name = f"pandas-pr-{pr_number}"

#     volumes_dict = {
#         "/home/MYID/compiler-pr-analysis/data/test_augmentation/002_pandas/pr/test_cases": {
#             "bind": "/workspace/test",
#             "mode": "rw"
#         },
#         "/home/MYID/compiler-pr-analysis/data/test_augmentation/002_pandas/pr/diffs": {
#             "bind": "/workspace/diffs",
#             "mode": "rw"
#         },
#         "/home/MYID/compiler-pr-analysis/docker/pandas/util": {
#             "bind": "/workspace/util",
#             "mode": "rw"
#         },
#     }

#     container = None
#     try:
#         # 1) Start the container with the volumes attached
#         container = start_container(
#             image_name=image_name,
#             volumes_dict=volumes_dict
#         )

#         # 2) Run a shell command to echo environment info
#         cmd_echo = ["/bin/bash", "-c", "echo $PR_NUMBER && echo $PWD"]
#         output_echo = execute_command(container, cmd_echo)
#         print(f"[Echo Command Output]\n{output_echo}")

#         # Simple assertions for the echo command:
#         assert pr_number in output_echo, "PR_NUMBER wasn't echoed as expected."
#         assert "/workspace" in output_echo, "PWD doesn't match expected workspace path."

#         ls_cmd = ["/bin/bash", "-c", "ls -l /workspace/test"]  # or whatever the path is
#         output_ls = execute_command(container, ls_cmd)
#         print(f"[List of /workspace/test directory]\n{output_ls}")

#         # check_cmds = [
#         #     ["which", "pytest"],

#         #     ["/usr/local/bin/pytest", "--version"],
#         # ]
#         # for cmd in check_cmds:
#         #     output_check = execute_command(container, cmd, suppress=True)
#         #     print(f"[Check command: {cmd}]\n{output_check}")

#         # Try this
#         command = [
#             "/bin/bash",
#             "-c",
#             f"cd /workspace && pytest --help"
#         ]
#         # pytest --cov=pandas --cov-report=xml test
#         output = execute_command(container, command, suppress=True)
#         print(f"[Pytest Output]\n{output}")

#         # 3) Now run pytest to generate coverage

#         # cmd_pytest = ["pytest", "--cov=pandas", "--cov-report=xml", "/workspace/test"]
#         # # cmd_pytest = ["ls", "/workspace/test"]
#         # output_pytest = execute_command(container, cmd_pytest)
#         # print(f"[Pytest Coverage Output]\n{output_pytest}")

#         # (Optional) You can add assertions if there's specific output you're expecting:
#         # e.g., check coverage XML was produced, etc.

#     except APIError as e:
#         pytest.fail(f"Docker API error occurred: {e}")
#     finally:
#         if container:
#             clean_up_container(container)
#             pass

# @pytest.mark.parametrize("pr_number", ["60628"])
# def test_run_pytest_in_container(pr_number):
#     """
#     This test reproduces the manual Docker command but adds another command afterward:
#       docker run ... /bin/bash -c "
#          cd /workspace &&
#          pytest --cov=pandas --cov-report=xml test &&
#          python util/test_relevance.py diffs/$PR_NUMBER.diff coverage.xml
#       "
#     """
#     client = docker.from_env()

#     host_path = os.getcwd()
#     volumes = {
#         f"{host_path}/data/test_augmentation/002_pandas/pr/test_cases": {
#             "bind": "/workspace/test",
#             "mode": "rw"
#         },
#         f"{host_path}/data/test_augmentation/002_pandas/pr/diffs": {
#             "bind": "/workspace/diffs",
#             "mode": "rw"
#         },
#         f"{host_path}/docker/pandas/util": {
#             "bind": "/workspace/util",
#             "mode": "rw"
#         }
#     }

#     image_name = f"pandas-pr-{pr_number}"

#     # ONE shell command that does multiple steps:
#     command = [
#         "/bin/bash",
#         "-c",
#         (
#             "cd /workspace && "
#             "pytest --cov=pandas --cov-report=xml test && "
#             f"python util/test_relevance.py diffs/{pr_number}.diff coverage.xml"
#         )
#     ]

#     container = None
#     try:
#         container = client.containers.run(
#             image=image_name,
#             command=command,
#             volumes=volumes,
#             tty=True,
#             stdin_open=True,
#             detach=True,
#             remove=True,
#             working_dir="/workspace",
#         )

#         logs_iter = container.logs(stream=True)
#         for line in logs_iter:
#             print(line.decode(), end="")

#         exit_status = container.wait()
#         status_code = exit_status.get("StatusCode", 1)
#         assert status_code == 0, (
#             f"Container exited with non-zero status code: {status_code}.\n"
#             "Check above logs for details."
#         )

#     except (docker.errors.APIError, docker.errors.NotFound) as e:
#         pytest.fail(f"Docker API error occurred: {e}")

#     finally:
#         if container:
#             try:
#                 container.stop()
#             except:
#                 pass


@pytest.mark.parametrize("pr_number", ["60628"])
@pytest.mark.skipif(not is_docker_image_available("pandas-pr-60628"),
                    reason="Docker image pandas-pr-60628 not available")
def test_run_combined_commands_in_container(pr_number):
    """
    This test reproduces the manual Docker command by combining
    multiple commands into a single bash command:

      docker run --rm -it \
        -v $(pwd)/data/test_augmentation/002_pandas/pr/test_cases:/workspace/test/ \
        -v $(pwd)/data/test_augmentation/002_pandas/pr/diffs:/workspace/diffs/ \
        -v $(pwd)/docker/pandas/util:/workspace/util \
        pandas-pr-${PR_NUMBER} \
        /bin/bash -c "cd /workspace && \
                      pytest --cov=pandas --cov-report=xml test && \
                      python util/test_relevance.py diffs/${PR_NUMBER}.diff coverage.xml"

    We do the same via the Docker SDK.
    """
    client = docker.from_env()

    host_path = os.getcwd()
    volumes = {
        f"{host_path}/data/test_augmentation/002_pandas/pr/test_cases": {
            "bind": "/workspace/test",
            "mode": "rw"
        },
        f"{host_path}/data/test_augmentation/002_pandas/pr/diffs": {
            "bind": "/workspace/diffs",
            "mode": "rw"
        },
        f"{host_path}/docker/pandas/util": {
            "bind": "/workspace/util",
            "mode": "rw"
        }
    }

    image_name = f"pandas-pr-{pr_number}"

    # Combine the commands into one bash string.
    # Note: if you want the container to expand the environment variable PR_NUMBER,
    # you can either pass it via the environment parameter or substitute using pr_number.
    # Here, we substitute using the Python variable.
    combined_command = (
        "cd /workspace && "
        "pytest --cov=pandas --cov-report=xml test > /dev/null 2>&1 ;"
        f"python util/test_relevance.py diffs/{pr_number}.diff coverage.xml > covdict.json"
    )
    command = ["/bin/bash", "-c", combined_command]

    container = None
    try:
        # Run the container with remove=True (so it auto-removes after exit)
        container = client.containers.run(
            image=image_name,
            command=command,
            volumes=volumes,
            tty=True,
            stdin_open=True,
            detach=True,
            remove=True,
            working_dir="/workspace",
            # Uncomment and set the user if needed:
            # user="regularuser",
        )

        # Stream logs from the container (use -s flag with pytest to see them live)
        logs = container.logs(stream=True)
        for line in logs:
            print(line.decode(), end="")

        # Wait for the container to exit and capture its exit status.
        exit_status = container.wait()
        status_code = exit_status.get("StatusCode", 1)
        assert status_code == 0, (
            f"Container exited with non-zero status code: {status_code}.\n"
            "Check above logs for details."
        )

    except (APIError, NotFound) as e:
        pytest.fail(f"Docker API error occurred: {e}")
    finally:
        if container:
            try:
                container.stop()
            except Exception:
                pass
