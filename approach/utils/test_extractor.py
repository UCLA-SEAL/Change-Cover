import ast
import sys
import json
import click
from typing import Set, Dict, Optional, List, Tuple
import os


class ExtractedFunction:
    def __init__(
            self,
            class_name: str,
            func_name: str,
            func_def: Optional[str] = None,
            file_path: Optional[str] = None):
        self.class_name = class_name
        self.func_name = func_name
        self.func_def = func_def
        self.file_path = file_path

    def __repr__(self):
        if self.class_name:
            return f"{self.class_name}.{self.func_name}"
        return self.func_name

    def __str__(self):
        return self.__repr__()

    def __hash__(self):
        return hash((self.class_name, self.func_name))

    def __eq__(self, other):
        if not isinstance(other, ExtractedFunction):
            return NotImplemented
        return self.__hash__() == other.__hash__()

    @property
    def full_str(self) -> str:
        """
        Return the full string representation of the function, including its definition.
        If the function definition is not available, return just the class and method names.
        """
        if self.func_def:
            if self.class_name:
                return f"{self.class_name}.{self.func_name}:\n{self.func_def}"
            else:
                return f"{self.func_name}:\n{self.func_def}"
        return f"{
            self.class_name}.{
            self.func_name}" if self.class_name else self.func_name

    def to_dict(self) -> Dict[str, Optional[str]]:
        """Convert the ExtractedFunction to a dictionary for JSON serialization."""
        return {
            'class_name': self.class_name,
            'func_name': self.func_name,
            'func_def': self.func_def,
            'file_path': self.file_path
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Optional[str]]) -> 'ExtractedFunction':
        """Create an ExtractedFunction from a dictionary (JSON deserialization)."""
        return cls(
            class_name=data['class_name'],
            func_name=data['func_name'],
            func_def=data.get('func_def'),
            file_path=data.get('file_path')
        )

    def to_json(self) -> str:
        """Convert the ExtractedFunction to a JSON string."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_json(cls, json_str: str) -> 'ExtractedFunction':
        """Create an ExtractedFunction from a JSON string."""
        data = json.loads(json_str)
        return cls.from_dict(data)


def extract_names(
        line: int,
        file_content: str,
        file_path: Optional[str]) -> ExtractedFunction:
    """
    Extract the class name, method name, and the full method definition from the given line of code.

    For example: scipy PR 22764

    463            class _VectorHessWrapper
    ...
    489            def _fd_hess(self, x, v, J0=None):
    490                if J0 is None:
    491                    J0 = self.jac(x) <-------------------line
    492                    self.njev += 1

    The output should be:
    (_VectorHessWrapper, _fd_hess, "def _fd_hess(self, x, v, J0=None):\n    if J0 is None:\n        ...")
    """

    # Parse the file content into an AST
    tree = ast.parse(file_content)

    # Split the file content into lines for extracting the function definition
    # later
    file_lines = file_content.splitlines()

    # Initialize variables to store the class and method names and function
    # definition
    class_name = None
    method_name = None
    function_definition = None

    # Define a visitor class to traverse the AST
    class NameExtractor(ast.NodeVisitor):
        def visit_ClassDef(self, node):
            nonlocal class_name
            # Calculate end_lineno if not available (for Python < 3.8)
            if not hasattr(node, 'end_lineno'):
                # Find the maximum line number of all child nodes
                max_line = node.lineno
                for child in ast.iter_child_nodes(node):
                    if hasattr(child, 'end_lineno'):
                        max_line = max(max_line, child.end_lineno)
                    else:
                        max_line = max(max_line, child.lineno)
                node.end_lineno = max_line

            # Check if the target line is within this class definition
            if node.lineno <= line <= node.end_lineno:
                class_name = node.name
                # Continue visiting child nodes to find nested methods
                self.generic_visit(node)

        def visit_FunctionDef(self, node):
            nonlocal method_name, function_definition
            # Calculate end_lineno if not available (for Python < 3.8)
            if not hasattr(node, 'end_lineno'):
                # Find the maximum line number of all child nodes
                max_line = node.lineno
                for child in ast.iter_child_nodes(node):
                    if hasattr(child, 'end_lineno'):
                        max_line = max(max_line, child.end_lineno)
                    else:
                        max_line = max(max_line, child.lineno)
                node.end_lineno = max_line

            # Check if the target line is within this function definition
            if node.lineno <= line <= node.end_lineno:
                method_name = node.name

                # Extract the full function definition from the source code
                # Adjust for 0-based indexing in the file_lines list
                start_idx = node.lineno - 1
                end_idx = node.end_lineno

                # Extract the function lines and join them into a single string
                function_lines = file_lines[start_idx:end_idx]
                function_definition = '\n'.join(function_lines)

                # Continue visiting child nodes to find any nested definitions
                self.generic_visit(node)

    # Create an instance of the visitor and visit the AST nodes
    extractor = NameExtractor()
    extractor.visit(tree)

    # check if we have a match
    if method_name is None:
        raise ValueError(
            f"Could not find a method definition at line {line} in the provided file content")

    return ExtractedFunction(
        class_name,
        method_name,
        function_definition,
        file_path)


class TestExtractor(ast.NodeVisitor):
    def __init__(self, target_class: Optional[str], target_method: str):
        self.target_class = target_class
        self.target_method = target_method
        self.required_nodes: List[ast.AST] = []
        self.current_class: Optional[str] = None
        self.found_target = False
        self.imported_names: Dict[str, str] = {}  # name -> module
        self.in_target_class = False
        self.target_method_node: Optional[ast.FunctionDef] = None
        self.fixture_nodes: Dict[str, ast.FunctionDef] = {}
        self.helper_functions: Dict[str, ast.FunctionDef] = {}

    def is_test_method(self, method_name: str) -> bool:
        """Determine if a method is a test method based on naming convention."""
        return method_name.startswith('test_')

    def is_fixture(self, node: ast.FunctionDef) -> bool:
        """Check if function is a pytest fixture."""
        for decorator in node.decorator_list:
            if (isinstance(decorator, ast.Call) and
                    isinstance(decorator.func, (ast.Name, ast.Attribute))):
                attr_name = decorator.func.attr if isinstance(
                    decorator.func, ast.Attribute) else decorator.func.id
                if attr_name == 'fixture':
                    return True
            elif isinstance(decorator, ast.Name) and decorator.id in ('fixture', 'pytest.fixture'):
                return True
        return False

    def visit_Import(self, node: ast.Import) -> None:
        self.required_nodes.append(node)
        for alias in node.names:
            self.imported_names[alias.name] = alias.name

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self.required_nodes.append(node)
        module = node.module if node.module else ''
        for alias in node.names:
            full_name = f"{module}.{alias.name}" if module else alias.name
            self.imported_names[alias.name] = full_name

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        old_class = self.current_class
        self.current_class = node.name

        if self.target_class and node.name == self.target_class:
            self.in_target_class = True

            new_class = ast.ClassDef(
                name=node.name,
                bases=node.bases,
                keywords=node.keywords,
                body=[],
                decorator_list=node.decorator_list
            )

            for child in node.body:
                if isinstance(child, ast.FunctionDef):
                    if child.name == self.target_method:
                        self.found_target = True
                        self.target_method_node = child
                        new_class.body.append(child)
                    elif not self.is_test_method(child.name):
                        new_class.body.append(child)
                elif isinstance(child, (ast.Assign, ast.AnnAssign)):
                    new_class.body.append(child)

            if self.found_target:
                self.required_nodes.append(new_class)

            self.in_target_class = False
        self.current_class = old_class

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        # Handle standalone test functions
        if self.target_class is None and node.name == self.target_method:
            self.found_target = True
            self.target_method_node = node
            self.required_nodes.append(node)
            return

        # Collect all top-level functions
        if not self.current_class:
            if self.is_fixture(node):
                self.fixture_nodes[node.name] = node
            elif not self.is_test_method(node.name):
                self.helper_functions[node.name] = node

    def visit_Assign(self, node: ast.Assign) -> None:
        if not self.current_class:
            self.required_nodes.append(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if not self.current_class:
            self.required_nodes.append(node)

    def visit_Expr(self, node: ast.Expr) -> None:
        if not self.current_class:
            self.required_nodes.append(node)


def extract_test_context(
        source: str,
        target_class: Optional[str],
        target_method: str) -> str:
    tree = ast.parse(source)
    extractor = TestExtractor(target_class, target_method)
    extractor.visit(tree)

    if not extractor.found_target:
        if target_class:
            raise ValueError(
                f"Target method '{target_class}.{target_method}' not found in the file")
        else:
            raise ValueError(
                f"Target function '{target_method}' not found in the file")

    # Include all fixtures and helper functions in their original order
    all_functions = list(extractor.fixture_nodes.values()) + \
        list(extractor.helper_functions.values())
    all_functions.sort(key=lambda x: x.lineno)
    for func in all_functions:
        extractor.required_nodes.append(func)

    # Add pytest import
    pytest_import = ast.ImportFrom(
        module='pytest', names=[
            ast.alias(
                name='mark', asname=None), ast.alias(
                name='fixture', asname=None)], level=0)
    extractor.required_nodes.insert(0, pytest_import)

    # Generate new source code
    new_tree = ast.Module(body=extractor.required_nodes, type_ignores=[])
    ast.fix_missing_locations(new_tree)

    new_source = ast.unparse(new_tree)
    return new_source


@click.command()
@click.argument('test_path', type=click.Path(exists=True))
@click.argument('target_class', required=False)
@click.argument('target_method')
@click.option('--output', '-o', type=click.Path(), help='Output file path')
@click.option('--verbose', '-v', is_flag=True, help='Enable verbose output')
def main(
        test_path: str,
        target_class: Optional[str],
        target_method: str,
        output: Optional[str],
        verbose: bool):
    """Extract a test method with all its dependencies from a test file."""
    if target_class and target_class.lower() == 'none':
        target_class = None

    with open(test_path, 'r') as f:
        source = f.read()

    if verbose:
        if target_class:
            click.echo(
                f"Extracting {target_class}.{target_method} from {test_path}...")
        else:
            click.echo(f"Extracting {target_method} from {test_path}...")

    try:
        extracted = extract_test_context(source, target_class, target_method)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    if output:
        os.makedirs(os.path.dirname(output) or '.', exist_ok=True)
        with open(output, 'w') as f:
            f.write(extracted)
        if verbose:
            click.echo(f"Successfully wrote to {output}")
    else:
        click.echo(extracted)


if __name__ == "__main__":
    if len(sys.argv) == 3:
        sys.argv.insert(2, "None")
    main()
