import subprocess
from pathlib import Path
from typing import List, Optional
import click
from rich.console import Console

"""
This script generates a Dockerfile for each Pull Request (PR) to build a Docker image with the specific PR.

Arguments:
--txt_pr_list (str): The path to the text file containing the list of PRs.


Steps:
1. Iterate over the list of PRs.
2. For each PR, generate a Dockerfile using the `docker build` command with the following arguments:
    - `PR_NUMBER`: The number of the PR.
    - `UID`: The user ID of the current user.
    - `GID`: The group ID of the current user.
3. Tag the Docker image with the PR number.
4. The Dockerfile is located in the `.devcontainer` folder, so navigate to this directory before running the command.

Example command to generate a Dockerfile for PR number 13370:
```
docker build --build-arg PR_NUMBER=13370 --build-arg UID=$(id -u) --build-arg GID=$(id -g) -t pr-13370 .
```

# Implementation Details
- The script uses the `subprocess` module to run the `docker build` command.
- The `subprocess.run` function is used to run the command.


# Style
- use subfunctions appropriately
- each function has at maximum 7 lines of code of content, break them to smaller functions otherwise
- avoid function with a single line which is a function call
- always use named arguments when calling a function
    (except for standard library functions)
- keep the style consistent to pep8 (max 80 char)
- to print the logs it uses the console from Rich library
- make sure to have docstring for each subfunction and keep it brief to the point
(also avoid comments on top of the functions)
- it uses pathlib every time that paths are checked, created or composed.
- use type annotations with typing List, Dict, Any, Tuple, Optional as appropriate
- make sure that any output folder exists before storing file in it, otherwise create it.

Convert the function above into a click v8 interface in Python.
- map all the arguments to a corresponding option (in click) which is required
- add all the default values of the arguments as default of the click options
- use only underscores
- add a main with the command
- add the required imports

# Example usage:
# python -m approach.utils.prepare_docker_files --dockerfile /path/to/dockerfile_diff --proj repoName --txt_pr_list /path/to/pr_list.txt

"""
console = Console(color_system=None)


def read_pr_list(txt_pr_list: str) -> List[str]:
    """Read the list of PRs from the given text file.

    It skips lines starting with '#' and removes leading/trailing whitespaces.
    """
    with open(txt_pr_list, 'r') as file:
        return [line.strip() for line in file if not line.startswith('#')]


def generate_dockerfile(
        dockerfile: str, proj: str, pr_number: str, uid: str, gid: str,
        img_suffix: str) -> None:
    """Build a docker image for the given PR number."""
    if img_suffix:
        name = f'{proj}-pr-{pr_number}-{img_suffix}'
    else:
        name = f'{proj}-pr-{pr_number}'
    command = [
        'docker', 'build',
        '-f', str(Path(dockerfile)),
        '--build-arg', f'PR_NUMBER={pr_number}',
        '--build-arg', f'UID={uid}',
        '--build-arg', f'GID={gid}',
        '-t', name,
        '.'
    ]
    print(' '.join(command))
    subprocess.run(command, check=True)


def build_docker_image(
        dockerfile: str, uid: str, gid: str, image_name: str) -> None:
    """Build a Docker image for the given PR number."""
    command = [
        'docker', 'build',
        '-f', str(Path(dockerfile)),
        '--build-arg', f'UID={uid}',
        '--build-arg', f'GID={gid}',
        '-t', image_name,
        '.'
    ]
    print(' '.join(command))
    subprocess.run(command, check=True)


@click.command()
@click.option('--dockerfile', required=False, type=str,
              default='.devcontainer/Dockerfile',)
@click.option('--proj', required=False, type=str, default='unknown')
@click.option('--txt_pr_list', required=True, type=str,
              help='Path to the text file containing the list of PRs.')
@click.option('--img_suffix', required=False, type=str, default=None)
def main(dockerfile: str, proj: str, txt_pr_list: str,
         img_suffix: Optional[str] = None) -> None:
    """Main function to build Docker image for each PR in the list."""
    pr_list = read_pr_list(txt_pr_list)
    uid = subprocess.check_output(['id', '-u']).decode().strip()
    gid = subprocess.check_output(['id', '-g']).decode().strip()
    for pr_number in pr_list:
        console.log(f'Using Dockerfile {dockerfile} for PR #{pr_number}')
        generate_dockerfile(dockerfile, proj, pr_number, uid, gid, img_suffix)


if __name__ == '__main__':
    main()
