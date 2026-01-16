import ast
from approach.scoping.spot_code_difference import (
    remove_docstring_and_comments,
    has_only_documentation_changes,
)


def test_remove_docstring_and_comments_function_def():
    """Test that function docstrings are removed."""
    code = """
def foo():
    \"\"\"This is a docstring.\"\"\"
    pass
"""
    tree = ast.parse(code)
    cleaned_tree = remove_docstring_and_comments(tree)
    assert ast.dump(cleaned_tree) == ast.dump(
        ast.parse("def foo():\n    pass\n"))


def test_remove_docstring_and_comments_class_def():
    """Test that class docstrings are removed."""
    code = """
class Foo:
    \"\"\"This is a docstring.\"\"\"
    def bar(self):
        pass
"""
    tree = ast.parse(code)
    cleaned_tree = remove_docstring_and_comments(tree)
    expected_code = """
class Foo:
    def bar(self):
        pass
"""
    assert ast.dump(cleaned_tree) == ast.dump(ast.parse(expected_code))


def test_remove_docstring_and_comments_module_level():
    """Test that module-level docstrings are removed."""
    code = """
\"\"\"This is a module docstring.\"\"\"
def foo():
    pass
"""
    tree = ast.parse(code)
    cleaned_tree = remove_docstring_and_comments(tree)
    expected_code = """
def foo():
    pass
"""
    assert ast.dump(cleaned_tree) == ast.dump(ast.parse(expected_code))


def test_remove_docstring_and_comments_no_docstrings():
    """Test that code without docstrings remains unchanged."""
    code = """
def foo():
    pass

class Bar:
    def baz(self):
        pass
"""
    tree = ast.parse(code)
    cleaned_tree = remove_docstring_and_comments(tree)
    assert ast.dump(cleaned_tree) == ast.dump(ast.parse(code))


def test_remove_docstring_and_comments_with_comments():
    """Test that comments are not removed (only docstrings)."""
    code = """
# This is a comment
def foo():
    \"\"\"This is a docstring.\"\"\"
    pass
"""
    tree = ast.parse(code)
    cleaned_tree = remove_docstring_and_comments(tree)
    expected_code = """
# This is a comment
def foo():
    pass
"""
    assert ast.dump(cleaned_tree) == ast.dump(ast.parse(expected_code))


def test_remove_comments_and_not_strings():
    """Test that only comments are removed, not strings."""
    code = """
# This is a comment
def foo():
    \"\"\"This is a docstring.\"\"\"
    a = 'This is a string'
    pass
"""
    tree = ast.parse(code)
    cleaned_tree = remove_docstring_and_comments(tree)
    expected_code = """
def foo():
    a = 'This is a string'
    pass
"""
    assert ast.dump(cleaned_tree) == ast.dump(ast.parse(expected_code))


def test_has_only_documentation_changes():
    """Test that only documentation changes are detected correctly."""
    repo_owner = "Qiskit"
    repo_name = "qiskit"
    pull_request_number = 13607

    result = has_only_documentation_changes(
        repo_owner, repo_name, pull_request_number)
    assert result is True


def test_more_than_documentation_changes():
    """Test that non-documentation changes are detected correctly."""
    repo_owner = "Qiskit"
    repo_name = "qiskit"
    pull_request_number = 13652

    result = has_only_documentation_changes(
        repo_owner, repo_name, pull_request_number)
    assert result is False
