from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import requests
import click
from rich.console import Console
import ast
import re
import warnings

console = Console(color_system=None)


def read_github_token(token_path: Path) -> str:
    """Read GitHub token from a file."""
    return token_path.read_text().strip()


def create_headers(token: str = None) -> Dict[str, str]:
    """Create headers for GitHub API requests."""
    if token is None:
        default_path = Path("secrets/github_token.txt")
        if not default_path.exists():
            raise ValueError(
                f"Token path {default_path} does not exist. Please provide a valid token path.")
        token = read_github_token(token_path=default_path)
    return {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
    }


def run_query(query: str, variables: Dict[str, Any],
              headers: Dict[str, str]) -> Dict[str, Any]:
    """Run a GraphQL query against the GitHub API."""
    response = requests.post(
        url='https://api.github.com/graphql',
        json={'query': query, 'variables': variables},
        headers=headers
    )
    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(
            f"Query failed with status code {response.status_code}: {response.text}"
        )


def get_pr_title_and_labels(
        owner: str, name: str, number: int, headers: Dict[str, str]) -> str:
    """Get the title and labels of a pull request."""
    query = """
    query($owner: String!, $name: String!, $number: Int!) {
      repository(owner: $owner, name: $name) {
        pullRequest(number: $number) {
          title
          labels(first: 10) {
            nodes {
              name
            }
          }
        }
      }
    }
    """
    variables = {'owner': owner, 'name': name, 'number': number}
    result = run_query(query=query, variables=variables, headers=headers)
    pull_request = result['data']['repository']['pullRequest']
    title = pull_request['title']
    labels = [label['name'] for label in pull_request['labels']['nodes']]
    return title, labels


def get_pr_commits(owner: str, name: str, number: int, headers: Dict
                   [str, str]) -> Tuple[str, str, List[Dict[str, Any]]]:
    """Get the base and head commits of a pull request."""
    query = """
    query($owner: String!, $name: String!, $number: Int!) {
      repository(owner: $owner, name: $name) {
        pullRequest(number: $number) {
          baseRefOid
          headRefOid
          files(first: 100) {
            nodes {
              path
              changeType
            }
          }
        }
      }
    }
    """
    variables = {'owner': owner, 'name': name, 'number': number}
    result = run_query(query=query, variables=variables, headers=headers)
    pull_request = result['data']['repository']['pullRequest']
    return pull_request['baseRefOid'], pull_request['headRefOid'], pull_request['files']['nodes']


def get_file_content(owner: str, name: str, expression: str,
                     headers: Dict[str, str]) -> Optional[str]:
    """Fetch file content at a specific commit."""
    query = """
    query($owner: String!, $name: String!, $expression: String!) {
      repository(owner: $owner, name: $name) {
        object(expression: $expression) {
          ... on Blob {
            text
          }
        }
      }
    }
    """
    variables = {'owner': owner, 'name': name, 'expression': expression}
    result = run_query(query=query, variables=variables, headers=headers)
    return result['data']['repository']['object']['text'] if result['data']['repository']['object'] else None


def fetch_file_contents(owner: str, name: str, base_commit: str,
                        head_commit: str, changed_files: List
                        [Dict[str, Any]],
                        headers: Dict[str, str] = None,
                        ignore_non_python: bool = False) -> List[Dict[str, Any]]:
    """Fetch file contents at base and head commits.

    Args:
    changed_files (List[Dict[str, Any]]): A list of dictionaries representing the changed files. Each dictionary should have the following keys:
            - 'path' (str): The file path.
            - 'changeType' (str): The type of change ('ADDED', 'MODIFIED', 'RENAMED').
    """
    if headers is None:
        headers = create_headers()
    file_contents = []
    for file in changed_files:
        file_path = file['path']
        if ignore_non_python and not file_path.endswith('.py'):
            continue
        change_type = file['changeType']
        base_content = None
        head_content = None

        if change_type in ['MODIFIED', 'RENAMED']:
            base_expression = f"{base_commit}:{file_path}"
            base_content = get_file_content(
                owner=owner, name=name, expression=base_expression,
                headers=headers)

        if change_type in ['ADDED', 'MODIFIED', 'RENAMED']:
            head_expression = f"{head_commit}:{file_path}"
            head_content = get_file_content(
                owner=owner, name=name, expression=head_expression,
                headers=headers)

        file_contents.append({
            'path': file_path,
            'change_type': change_type,
            'base_content': base_content,
            'head_content': head_content,
        })
    return file_contents


def print_file_contents(file_contents: List[Dict[str, Any]]) -> None:
    """Print the contents of the files."""
    for file in file_contents:
        console.print(f"File: {file['path']}")
        console.print(f"Change Type: {file['change_type']}")
        console.print("Content Before (Base):")
        console.print(
            file['base_content']
            or "File does not exist in base commit.")
        console.print("Content After (Head):")
        console.print(
            file['head_content']
            or "File does not exist in head commit.")
        console.print("=" * 80)


def remove_docstring_and_comments(ast_tree: ast.AST) -> ast.AST:
    """
    Remove docstrings and comments from an AST.

    Args:
        ast_tree (ast.AST): The abstract syntax tree to process.

    Returns:
        ast.AST: The processed AST with docstrings and comments removed.
    """
    class RemoveDocstringAndComments(ast.NodeTransformer):
        def visit_FunctionDef(self, node):
            self.generic_visit(node)
            if node.body and isinstance(
                    node.body[0],
                    ast.Expr) and isinstance(
                    node.body[0].value, ast.Str):
                node.body = node.body[1:]
            return node

        def visit_ClassDef(self, node):
            self.generic_visit(node)
            if node.body and isinstance(
                    node.body[0],
                    ast.Expr) and isinstance(
                    node.body[0].value, ast.Str):
                node.body = node.body[1:]
            return node

        def visit_Module(self, node):
            self.generic_visit(node)
            if node.body and isinstance(
                    node.body[0],
                    ast.Expr) and isinstance(
                    node.body[0].value, ast.Str):
                node.body = node.body[1:]
            return node

        def visit_Expr(self, node):
            if isinstance(node.value, ast.Str):
                return None
            return node

    return RemoveDocstringAndComments().visit(ast_tree)


def is_code_changed(base_content: str, head_content: str) -> bool:
    """Determine if the code has changed by comparing ASTs."""
    try:
        base_tree = ast.parse(base_content) if base_content else None
        head_tree = ast.parse(head_content) if head_content else None
        cleaned_base_tree = remove_docstring_and_comments(base_tree)
        cleaned_head_tree = remove_docstring_and_comments(head_tree)
        return ast.dump(cleaned_base_tree) != ast.dump(cleaned_head_tree)
    except SyntaxError as e:
        console.print(f"Syntax error while parsing AST: {e}", style="red")
        return True


@click.group()
def cli():
    """Main entry point for the CLI."""
    pass


@cli.command()
@click.option('--token_path', required=True, type=Path,
              default=Path("secrets/github_token.txt"),
              help='Path to GitHub token file.')
@click.option('--repo_owner', required=True, type=str, default='Qiskit',
              help='Repository owner.')
@click.option('--repo_name', required=True, type=str, default='qiskit',
              help='Repository name.')
@click.option('--pull_request_number', required=True, type=int, default=13551,
              help='Pull request number.')
@click.option('--ignore_non_python', is_flag=True, default=False,
              help='Ignore non-Python files.')
def show_diff(token_path: Path, repo_owner: str, repo_name: str,
              pull_request_number: int, ignore_non_python: bool) -> None:
    """Fetch and print file differences in a pull request."""
    token = read_github_token(token_path=token_path)
    headers = create_headers(token=token)
    base_commit, head_commit, changed_files = get_pr_commits(
        owner=repo_owner, name=repo_name, number=pull_request_number, headers=headers)
    file_contents = fetch_file_contents(
        owner=repo_owner, name=repo_name, base_commit=base_commit,
        head_commit=head_commit, changed_files=changed_files, headers=headers,
        ignore_non_python=ignore_non_python)
    print_file_contents(file_contents=file_contents)


def has_only_documentation_changes(
        repo_owner: str, repo_name: str, pull_request_number: int,
        token_path: Optional[Path] = None,
        regex_to_include_files: Optional[str] = None,
        regex_to_exclude_files: Optional[str] = None,
        ignore_non_python: bool = False) -> bool:
    """Check if the changes in a pull request are only in docstrings/comments."""
    if token_path is None:
        token_path = Path("secrets/github_token.txt")
    if not token_path.exists():
        warnings.warn(
            f"Token path {token_path} does not exist. Please provide a valid token path.")
        return False

    token = read_github_token(token_path=token_path)
    headers = create_headers(token=token)
    title, labels = get_pr_title_and_labels(
        owner=repo_owner, name=repo_name, number=pull_request_number,
        headers=headers)

    # If the title contains 'DOC:' and the label contains 'Documentation/Docs', consider it as a documentation-only change.
    # Note: occationally PRs that make little trivial changes are also titled with 'DOC:', we can treat them as documentation-only changes.
    # For example: https://github.com/scipy/scipy/pull/22376. Updates the name
    # an imported package.
    if repo_name == 'scipy':
        if 'DOC:' in title and 'Documentation' in labels:
            console.print(
                f"Only documentation changes in the pull request {pull_request_number}.",
                style="yellow")
            return True
    elif repo_name == 'pandas':
        if 'DOC:' in title and 'Docs' in labels:
            console.print(
                f"Only documentation changes in the pull request {pull_request_number}.",
                style="yellow")
            return True
    elif repo_name == 'qiskit':
        pass

    base_commit, head_commit, changed_files = get_pr_commits(
        owner=repo_owner, name=repo_name,
        number=pull_request_number, headers=headers)
    if regex_to_include_files:
        changed_files = [
            file for file in changed_files
            if re.match(regex_to_include_files, file['path'])]
    if regex_to_exclude_files:
        changed_files = [
            file for file in changed_files
            if not re.match(regex_to_exclude_files, file['path'])]
    file_contents = fetch_file_contents(
        owner=repo_owner, name=repo_name, base_commit=base_commit,
        head_commit=head_commit, changed_files=changed_files, headers=headers,
        ignore_non_python=ignore_non_python)

    for file in file_contents:
        if file['base_content'] and file['head_content']:
            if is_code_changed(file['base_content'], file['head_content']):
                console.print(
                    f"Code has changed in file (beyond the documentation): {file['path']}")
                return False

    console.print("Only documentation changes in the pull request.")
    return True


@cli.command()
@click.option('--token_path', required=False, type=Path,
              default=None,
              help='Path to GitHub token file.')
@click.option('--repo_owner', required=True, type=str, default='Qiskit',
              help='Repository owner.')
@click.option('--repo_name', required=True, type=str, default='qiskit',
              help='Repository name.')
@click.option('--pull_request_number', required=True, type=int, default=13551,
              help='Pull request number.')
@click.option('--ignore_non_python', is_flag=True, default=False,
              help='Ignore non-Python files.')
def check_code_change(
        token_path: Optional[Path],
        repo_owner: str, repo_name: str, pull_request_number: int,
        ignore_non_python: bool) -> None:
    """Check if the changes in a pull request are only in docstrings/comments."""
    result = has_only_documentation_changes(
        repo_owner, repo_name, pull_request_number, token_path,
        ignore_non_python)
    console.print(result)


if __name__ == '__main__':
    cli()
    # Example usage:
    # python -m approach.scoping.spot_code_difference show-diff --token_path secrets/github_token.txt --repo_owner Qiskit --repo_name qiskit --pull_request_number 13551 --ignore_non_python
    # python -m approach.scoping.spot_code_difference check-code-change
    # --token_path secrets/github_token.txt --repo_owner Qiskit --repo_name
    # qiskit --pull_request_number 13554 --ignore_non_python
