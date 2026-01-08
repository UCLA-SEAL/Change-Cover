import pytest
from pathlib import Path
import json

from approach.coverage.formatter import (
    load_json,
    concatenate_files,
    read_file,
    append_custom_string,
    format_file_content,
    write_output_file,
    process_json_file,
    get_lines_of_function_signature,
    get_lines_of_class_definition
)


@pytest.fixture
def temp_dir(tmp_path):
    return tmp_path


@pytest.fixture
def json_file(temp_dir):
    data = {
        "test_file.py": {
            "covered": [1, 2, 3],
            "missed": [4]
        }
    }
    json_path = temp_dir / "current_relevance.json"
    with json_path.open('w') as f:
        json.dump(data, f)
    return json_path


@pytest.fixture
def source_file_dir(temp_dir):
    source_dir = temp_dir / "after"
    source_dir.mkdir()
    file_content = [
        "# Line 1\n",
        "# Line 2\n",
        "# Line 3\n",
        "# Line 4\n"
    ]
    file_path = source_dir / "test_file.py"
    with file_path.open('w') as f:
        f.writelines(file_content)
    return source_dir


@pytest.fixture
def two_files_json_file(temp_dir):
    data = {
        "file1.py": {
            "covered": [1, 2, 3],
            "missed": [4]
        },
        "fake_subdir/file2.py": {
            "covered": [1, 2],
            "missed": [3]
        }
    }
    json_path = temp_dir / "current_relevance.json"
    with json_path.open('w') as f:
        json.dump(data, f)
    return json_path


@pytest.fixture
def two_files_source_file_1_dir(temp_dir):
    source_dir = temp_dir / "after"
    source_dir.mkdir()
    file_content = [
        "# Line 1\n",
        "# Line 2\n",
        "# Line 3\n",
        "# Line 4\n"
    ]
    file_path = source_dir / "file1.py"
    with file_path.open('w') as f:
        f.writelines(file_content)
    return source_dir


@pytest.fixture
def two_files_source_file_2_dir(temp_dir):
    source_dir = temp_dir / "after"
    full_path = Path("fake_subdir") / "file2.py"
    file_content = [
        "# Line 1\n",
        "# Line 2\n",
        "# Line 3\n"
    ]
    Path(source_dir / "fake_subdir").mkdir(parents=True)
    file_path = source_dir / full_path
    with file_path.open('w') as f:
        f.writelines(file_content)
    return source_dir


def test_format_file_content():
    """Test that the file content is formatted correctly."""
    file_path = "test_file.py"
    file_content = [
        "# Line 1\n",
        "# Line 2\n",
        "# Line 3\n",
        "# Line 4  # UNCOVERED\n"
    ]
    formatted_content = format_file_content(file_path, file_content)
    expected_content = (
        "--------------------------------------------------------------------------------\n"
        "# test_file.py\n"
        "--------------------------------------------------------------------------------\n"
        "# Line 1\n"
        "# Line 2\n"
        "# Line 3\n"
        "# Line 4  # UNCOVERED\n\n"
        "--------------------------------------------------------------------------------")
    # print("&" * 80)
    # print(formatted_content)
    # print("&" * 80)
    # print(expected_content)
    # print("&" * 80)
    assert formatted_content == expected_content


def test_write_output_file(temp_dir):
    """Test that the output file is written correctly."""
    output_file = temp_dir / "pr_uncovered_lines.txt"
    content = "Test content"
    write_output_file(output_file, content)
    with output_file.open('r') as f:
        assert f.read() == content


def test_process_json_file(json_file, source_file_dir, temp_dir):
    """Test the entire process of reading JSON, processing files, and writing output."""
    output_file = temp_dir / "pr_uncovered_lines.txt"
    custom_string = "# UNCOVERED"
    process_json_file(
        json_file=json_file,
        source_dir=source_file_dir,
        output_file=output_file,
        custom_string=custom_string,
        context_size=3
    )
    with output_file.open('r') as f:
        content = f.read()
    expected_content = (
        "--------------------------------------------------------------------------------\n"
        "# test_file.py\n"
        "--------------------------------------------------------------------------------\n"
        "# Line 1\n"
        "# Line 2\n"
        "# Line 3\n"
        "# Line 4 # UNCOVERED\n\n"
        "--------------------------------------------------------------------------------")
    assert content == expected_content


def test_process_json_file_two_source_files(
        two_files_json_file, two_files_source_file_1_dir,
        two_files_source_file_2_dir, temp_dir):
    """Test the entire process of reading JSON, processing multiple files, and writing output."""
    output_file = temp_dir / "pr_uncovered_lines.txt"
    custom_string = "# UNCOVERED"
    process_json_file(
        json_file=two_files_json_file,
        source_dir=two_files_source_file_1_dir,
        output_file=output_file,
        custom_string=custom_string,
        context_size=3
    )
    process_json_file(
        json_file=two_files_json_file,
        source_dir=two_files_source_file_2_dir,
        output_file=output_file,
        custom_string=custom_string,
        context_size=3
    )
    with output_file.open('r') as f:
        content = f.read()
    expected_content = (
        "--------------------------------------------------------------------------------\n"
        "# file1.py\n"
        "--------------------------------------------------------------------------------\n"
        "# Line 1\n"
        "# Line 2\n"
        "# Line 3\n"
        "# Line 4 # UNCOVERED\n\n"
        "--------------------------------------------------------------------------------\n"
        "--------------------------------------------------------------------------------\n"
        "# fake_subdir/file2.py\n"
        "--------------------------------------------------------------------------------\n"
        "# Line 1\n"
        "# Line 2\n"
        "# Line 3 # UNCOVERED\n\n"
        "--------------------------------------------------------------------------------")
    assert content == expected_content


@pytest.fixture
def single_line_signatures():
    return [
        "def func1():\n",
        "    pass\n",
        "\n",
        "def func2(arg1, arg2):\n",
        "    return arg1 + arg2\n",
        "\n",
        "class MyClass:\n",
        "    def method1(self):\n",
        "        pass\n",
        "\n",
        "    def method2(self, arg):\n",
        "        return arg\n"
    ]


@pytest.fixture
def multi_line_signatures():
    return [
        "def func1(\n",
        "    arg1, arg2):\n",
        "    return arg1 + arg2\n",
        "\n",
        "class MyClass:\n",
        "    def method1(\n",
        "        self):\n",
        "        pass\n",
        "\n",
        "    def method2(\n",
        "        self, arg):\n",
        "        return arg\n"
    ]


def test_get_lines_of_function_signature(single_line_signatures):
    """Test that the function correctly identifies lines with function signatures."""
    expected_lines = [1, 4, 8, 11]
    assert get_lines_of_function_signature(
        single_line_signatures) == expected_lines


def test_get_lines_of_signatures_multilines(multi_line_signatures):
    """Test that the function correctly identifies lines with function signatures."""
    expected_lines = [1, 2, 6, 7, 10, 11]
    assert get_lines_of_function_signature(
        multi_line_signatures) == expected_lines


@pytest.fixture
def single_line_class_definitions():
    return [
        "class MyClass1:\n",
        "    pass\n",
        "\n",
        "class MyClass2:\n",
        "    def method(self):\n",
        "        pass\n"
    ]


@pytest.fixture
def multi_line_class_definitions():
    return [
        "class MyClass1(\n",
        "    BaseClass1, BaseClass2):\n",
        "    pass\n",
        "\n",
        "class MyClass2(\n",
        "    BaseClass1, BaseClass2):\n",
        "    def method(self):\n",
        "        pass\n"
    ]


def test_get_lines_of_class_definition_single_line(
        single_line_class_definitions):
    """Test that the function correctly identifies lines with single-line class definitions."""
    expected_lines = [1, 4]
    assert get_lines_of_class_definition(
        single_line_class_definitions) == expected_lines


def test_get_lines_of_class_definition_multi_line(multi_line_class_definitions):
    """Test that the function correctly identifies lines with multi-line class definitions."""
    expected_lines = [1, 2, 5, 6]
    assert get_lines_of_class_definition(
        multi_line_class_definitions) == expected_lines
