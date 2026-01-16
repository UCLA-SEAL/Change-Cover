import pytest
import ast
import re
import json
from approach.utils.merge_tests import merge_tests
from typing import List, Tuple, Set, Optional


class FunctionInfo:
    def __init__(
        self,
        name: str,
        class_name: Optional[str],
        decorators: List[str],
        full_source: str,
    ):
        self.name = name
        self.class_name = class_name
        self.decorators = decorators
        self.full_source = full_source.strip()

    def __repr__(self):
        cls = f"{self.class_name}." if self.class_name else ""
        return f"<FunctionInfo {cls}{self.name} decorators={self.decorators}>"

    def __eq__(self, value):
        return (
            isinstance(value, FunctionInfo) and
            self.name == value.name and
            self.class_name == value.class_name and
            self.decorators == value.decorators and
            self.full_source == value.full_source
        )


def extract_functions(source_code: str) -> List[FunctionInfo]:
    """
    Extracts function and method definitions from Python source code.

    Args:
        source_code (str): The source code to analyze.

    Returns:
        List[FunctionInfo]: A list of FunctionInfo objects for each function/method.
    """
    class FuncCollector(ast.NodeVisitor):
        def __init__(self, source_lines: List[str]):
            self.source_lines = source_lines
            self.funcs: List[FunctionInfo] = []
            self.class_stack: List[str] = []

        def visit_ClassDef(self, node: ast.ClassDef):
            self.class_stack.append(node.name)
            self.generic_visit(node)
            self.class_stack.pop()

        def visit_FunctionDef(self, node: ast.FunctionDef):
            class_name = self.class_stack[-1] if self.class_stack else None
            decorators = [ast.unparse(d) for d in node.decorator_list]
            start_line = node.lineno - 1  # 0-based
            # Best-effort to capture end using `end_lineno` (Python 3.8+)
            end_line = getattr(node, 'end_lineno', start_line + 1)
            full_source = ''.join(self.source_lines[start_line:end_line])
            self.funcs.append(FunctionInfo(
                name=node.name,
                class_name=class_name,
                decorators=decorators,
                full_source=full_source,
            ))
            self.generic_visit(node)

    tree = ast.parse(source_code)
    source_lines = source_code.splitlines(keepends=True)
    collector = FuncCollector(source_lines)
    collector.visit(tree)
    return collector.funcs


def assert_contains_function(functions, name, class_name=None):
    assert any(f.name == name and f.class_name == class_name for f in functions), \
        f"Expected to find function {class_name + '.' if class_name else ''}{name}, but didn't."


def assert_function_decorators(
        functions,
        name,
        expected_decorators,
        class_name=None):
    matched = [f for f in functions if f.name ==
               name and f.class_name == class_name]
    assert matched, f"No match found for function {class_name + '.' if class_name else ''}{name}"
    actual = matched[0].decorators
    for expected in expected_decorators:
        assert any(actual_decorator.startswith(expected) for actual_decorator in actual), \
            f"Expected decorator starting with '{expected}' not found in {actual}"


def assert_function_count(functions, expected_count):
    assert len(functions) == expected_count, \
        f"Expected {expected_count} functions, but found {len(functions)}."


def assert_function_set_superset(superset, subset, ignore_func_body=False):
    if ignore_func_body:
        superset = {(f.class_name, f.name) for f in superset}
        subset = {(f.class_name, f.name) for f in subset}
        assert subset.issubset(
            superset), f"Subset {subset} is not a subset of superset {superset}"
    else:
        for f in subset:
            assert f in superset, f"Function {f} missing from merged output."


class TestAddMode:

    def test_add_mode_new_test_func_with_helper_func(self):
        """
        Test merge_tests' "ADD" mode
        New test file contains a top level test func and its helper func,
        Both needs to be added to the existing test file
        """
        new_test_path = 'approach/utils/tests/new_test_1.py'
        existing_test_path = 'approach/utils/tests/existing_test_1.py'

        # check there
        # 1) exists only one top level test func in the new test file
        # 2) exists only one top level helper func in the new test file
        with open(new_test_path, 'r') as f:
            new_test_code = f.read()
        new_funcs = extract_functions(new_test_code)
        assert_function_count(new_funcs, 2)
        assert_contains_function(
            new_funcs, 'test_length_nonmasked_with_iterable_axis')
        assert_contains_function(new_funcs, 'get_arrays')

        # the list of funcs in the existing test file
        with open(existing_test_path, 'r') as f:
            existing_test_code = f.read()
        existing_funcs = extract_functions(existing_test_code)

        # Run merge_tests in ADD mode
        merged_test_str, merged_funcs_raw = merge_tests(
            new_src=new_test_code,
            base_src=existing_test_code,
            mode='ADD',
            mapping=None
        )

        # check the merged test str
        merged_funcs = extract_functions(merged_test_str)
        # the merged test file should contain exactly 2 more funcs than the
        # existing test file
        assert_function_count(merged_funcs, len(existing_funcs) + 2)
        # the merged test file should contain all funcs in the existing test
        # file
        assert_function_set_superset(merged_funcs, existing_funcs)
        # the merged test file should contain all funcs in the new test file
        assert_function_set_superset(merged_funcs, new_funcs)

    def test_add_mode_new_test_func_with_decorators(self):
        """
        Test merge_tests' "ADD" mode
        New test file contains a top level test func with decorators,
        """
        new_test_path = 'approach/utils/tests/new_test_2.py'
        existing_test_path = 'approach/utils/tests/existing_test_1.py'

        # check there
        # 1) exists only one top level test func in the new test file
        # 2) the top level test func has 1 decorator @mark.parametrize
        with open(new_test_path, 'r') as f:
            new_test_code = f.read()
        new_funcs = extract_functions(new_test_code)
        assert_function_count(new_funcs, 1)
        assert_contains_function(new_funcs, 'test_warning_suppression')
        assert_function_decorators(
            new_funcs,
            'test_warning_suppression',
            ['mark.parametrize'])

        # the list of funcs in the existing test file
        with open(existing_test_path, 'r') as f:
            existing_test_code = f.read()
        existing_funcs = extract_functions(existing_test_code)

        # Run merge_tests in ADD mode
        merged_test_str, merged_funcs_raw = merge_tests(
            new_src=new_test_code,
            base_src=existing_test_code,
            mode='ADD',
            mapping=None
        )

        # check the merged test str
        merged_funcs = extract_functions(merged_test_str)
        # the merged test file should contain exactly 1 more func than the
        # existing test file
        assert_function_count(merged_funcs, len(existing_funcs) + 1)
        # the merged test file should contain all funcs in the existing test
        # file
        assert_function_set_superset(merged_funcs, existing_funcs)
        # the merged test file should contain all funcs in the new test file
        assert_function_set_superset(merged_funcs, new_funcs)

    def test_add_mode_new_test_method(self):
        """
        Test merge_tests' "ADD" mode
        New test contains a test class with a test method
        The test class is already in the existing test file
        The test method needs to be added to the existing test class
        """

        new_test_path = 'approach/utils/tests/new_test_7.py'
        existing_test_path = 'approach/utils/tests/existing_test_2.py'

        # check there
        # 1) exists only one test class in the new test file
        # 2) exists 2 top-level helper funcs in the new test file
        with open(new_test_path, 'r') as f:
            new_test_code = f.read()
        new_funcs = extract_functions(new_test_code)
        assert_function_count(new_funcs, 3)
        assert_contains_function(new_funcs, 'test_dummy', class_name='TestLM')
        assert_contains_function(new_funcs, 'fun_trivial')
        assert_contains_function(new_funcs, 'jac_trivial')

        # the list of funcs in the existing test file
        with open(existing_test_path, 'r') as f:
            existing_test_code = f.read()
        existing_funcs = extract_functions(existing_test_code)
        # check the existing test file contains the test class TestLM
        assert any(f.class_name == 'TestLM'
                   for f in existing_funcs)
        # check the existing test file already contains the helper funcs
        assert_contains_function(existing_funcs, 'fun_trivial')
        assert_contains_function(existing_funcs, 'jac_trivial')

        # Run merge_tests in ADD mode
        merged_test_str, merged_funcs_raw = merge_tests(
            new_src=new_test_code,
            base_src=existing_test_code,
            mode='ADD',
            mapping=None
        )

        # check the merged test str
        merged_funcs = extract_functions(merged_test_str)
        # the merged test file should contain exactly 1 more func than the
        # existing test file
        assert_function_count(merged_funcs, len(existing_funcs) + 1)
        # the merged test file should contain all funcs in the existing test
        # file
        assert_function_set_superset(merged_funcs, existing_funcs)
        # the merged test file should contain all funcs in the new test file
        assert_function_set_superset(merged_funcs, new_funcs)

    def test_add_mode_new_test_method_with_decorators(self):
        """
        Test merge_tests' "ADD" mode
        New test contains a test class with a test method
        The test class is already in the existing test file
        The test method needs to be added to the existing test class
        """

        new_test_path = 'approach/utils/tests/new_test_3.py'
        existing_test_path = 'approach/utils/tests/existing_test_2.py'

        # check there
        # 1) exists only one test class in the new test file
        # 2) exists 2 top-level helper funcs in the new test file
        with open(new_test_path, 'r') as f:
            new_test_code = f.read()
        new_funcs = extract_functions(new_test_code)
        assert_function_count(new_funcs, 3)
        assert_contains_function(new_funcs, 'test_dummy', class_name='TestLM')
        assert_contains_function(new_funcs, 'fun_trivial')
        assert_contains_function(new_funcs, 'jac_trivial')

        # the list of funcs in the existing test file
        with open(existing_test_path, 'r') as f:
            existing_test_code = f.read()
        existing_funcs = extract_functions(existing_test_code)
        # check the existing test file contains the test class TestLM
        assert any(f.class_name == 'TestLM'
                   for f in existing_funcs)
        # check the existing test file already contains the helper funcs
        assert_contains_function(existing_funcs, 'fun_trivial')
        assert_contains_function(existing_funcs, 'jac_trivial')

        # Run merge_tests in ADD mode
        merged_test_str, merged_funcs_raw = merge_tests(
            new_src=new_test_code,
            base_src=existing_test_code,
            mode='ADD',
            mapping=None
        )

        # check the merged test str
        merged_funcs = extract_functions(merged_test_str)
        # the merged test file should contain exactly 1 more func than the
        # existing test file
        assert_function_count(merged_funcs, len(existing_funcs) + 1)
        # the merged test file should contain all funcs in the existing test
        # file
        assert_function_set_superset(merged_funcs, existing_funcs)
        # the merged test file should contain all funcs in the new test file
        assert_function_set_superset(merged_funcs, new_funcs)

    def test_issue_1(self):
        """
        Error observed in qiskit PR 14417
        Problem reduced to new test method WITHOUT decorator:
        see test_add_mode_new_test_method
        """
        new_test_path = 'approach/utils/tests/new_test_issue_1.py'
        existing_test_path = 'approach/utils/tests/test_consolidate_blocks.py'

        # check there
        # 1) exists only one test class in the new test file
        # 2) exists only one test method in the new test class
        with open(new_test_path, 'r') as f:
            new_test_code = f.read()
        new_funcs = extract_functions(new_test_code)
        assert_contains_function(
            new_funcs,
            'test_kak_gate_consolidation',
            class_name='TestConsolidateBlocks')

        # the list of funcs in the existing test file
        with open(existing_test_path, 'r') as f:
            existing_test_code = f.read()
        existing_funcs = extract_functions(existing_test_code)
        # check the existing test file contains the test class
        # TestConsolidateBlocks
        assert any(f.class_name == 'TestConsolidateBlocks'
                   for f in existing_funcs)

        # Run merge_tests in ADD mode
        merged_test_str, merged_funcs_raw = merge_tests(
            new_src=new_test_code,
            base_src=existing_test_code,
            mode='ADD',
            mapping=None
        )

        # print the merged test str for debugging
        print(merged_test_str)
        print(merged_funcs_raw)
        # save the merged test str to a file for debugging
        with open('approach/utils/tests/merged_test_issue_1.py', 'w') as f:
            f.write(merged_test_str)

        # check the merged test str
        merged_funcs = extract_functions(merged_test_str)
        # the merged test file should contain exactly 1 more func than the
        # existing test file
        assert_function_count(merged_funcs, len(existing_funcs) + 1)
        # the merged test file should contain all funcs in the existing test
        # file
        assert_function_set_superset(merged_funcs, existing_funcs)
        # the merged test file should contain all funcs in the new test file
        # this asserts indentation is preserved by matching the full body of
        # the test method
        assert_function_set_superset(merged_funcs, new_funcs)


class TestExtendMode:

    def test_extend_mode_new_test_func(self):
        """
        Test merge_tests' "EXTEND" mode
        New test file contains a top level test func,
        The test func needs to be added to the existing test file
        """
        new_test_path = 'approach/utils/tests/new_test_4.py'
        existing_test_path = 'approach/utils/tests/existing_test_3.py'
        mapping_path = 'approach/utils/tests/mapping_1.json'

        # check there
        # 1) exists only one top level test func in the new test file
        with open(new_test_path, 'r') as f:
            new_test_code = f.read()
        new_funcs = extract_functions(new_test_code)
        assert_function_count(new_funcs, 1)
        assert_contains_function(new_funcs, 'test_to_append')
        assert_function_decorators(new_funcs, 'test_to_append',
                                   ['pytest.mark.xslow'])

        # the list of funcs in the existing test file
        with open(existing_test_path, 'r') as f:
            existing_test_code = f.read()
        existing_funcs = extract_functions(existing_test_code)

        # mapping
        with open(mapping_path, 'r') as f:
            mapping = json.load(f)

        # Run merge_tests in EXTEND mode
        merged_test_str, merged_funcs_raw = merge_tests(
            new_src=new_test_code,
            base_src=existing_test_code,
            mode='APPEND',
            mapping=mapping
        )

        # check the merged test str
        merged_funcs = extract_functions(merged_test_str)
        # the merged test file should contain exactly same number of funcs
        assert_function_count(merged_funcs, len(existing_funcs))
        # the merged test file should contain all funcs in the existing test
        # file
        assert_function_set_superset(
            merged_funcs,
            existing_funcs,
            ignore_func_body=True)

        # find the "to_be_appended" func before and after the merge
        before = [f for f in existing_funcs if f.name == 'to_be_appended']
        after = [f for f in merged_funcs if f.name == 'to_be_appended']

        # to_be_appended func's body is still there
        assert after[0].full_source.startswith(before[0].full_source)
        # new test func is appended to the end of to_be_appended
        assert re.sub(
            r'\s+',
            '',
            after[0].full_source).endswith(
            re.sub(
                r'\s+',
                '',
                new_funcs[0].full_source).lstrip('deftest_to_append():'))

    def test_extend_mode_new_test_method(self):
        """
        Test merge_tests' "EXTEND" mode
        New test file contains a test class with a test method
        The test class is already in the existing test file
        The test method needs to be appended to the existing test class
        """
        new_test_path = 'approach/utils/tests/new_test_5.py'
        existing_test_path = 'approach/utils/tests/existing_test_3.py'
        mapping_path = 'approach/utils/tests/mapping_2.json'

        # check there
        # 1) exists only one test class in the new test file
        # 2) exists only one test method in the new test class
        with open(new_test_path, 'r') as f:
            new_test_code = f.read()
        new_funcs = extract_functions(new_test_code)

        assert_contains_function(
            new_funcs,
            'test_root_scalar_muller',
            class_name='Test_muller')
        assert_function_decorators(
            new_funcs, 'test_root_scalar_muller', [
                'skip_xp_backends', 'pytest.mark.parametrize'], class_name='Test_muller')

        # the list of funcs in the existing test file
        with open(existing_test_path, 'r') as f:
            existing_test_code = f.read()
        existing_funcs = extract_functions(existing_test_code)
        # check the existing test file contains the test class Test_muller
        assert any(f.class_name == 'Test_muller'
                   for f in existing_funcs)
        # check the existing test file contains the test method
        # test__muller_real_roots
        assert_contains_function(
            existing_funcs,
            'test__muller_real_roots',
            class_name='Test_muller')

        with open(mapping_path, 'r') as f:
            mapping = json.load(f)

        # Run merge_tests in EXTEND mode
        merged_test_str, merged_funcs_raw = merge_tests(
            new_src=new_test_code,
            base_src=existing_test_code,
            mode='APPEND',
            mapping=mapping
        )

        # check the merged test str
        merged_funcs = extract_functions(merged_test_str)
        # the merged test file should contain one more func
        # Note this is note the new test method itself, but the nested func inside it
        # See new_test_5.py for details
        assert_function_count(merged_funcs, len(existing_funcs) + 1)
        # the merged test file should contain all funcs in the existing test
        # file
        assert_function_set_superset(
            merged_funcs,
            existing_funcs,
            ignore_func_body=True)
        # find the test__muller_real_roots func before and after the merge
        before = [f for f in existing_funcs if f.name ==
                  'test__muller_real_roots']
        after = [f for f in merged_funcs if f.name ==
                 'test__muller_real_roots']

        # test__muller_real_roots func's body is still there
        assert after[0].full_source.startswith(before[0].full_source)
        # new test func is appended to the end of test__muller_real_roots
        assert re.sub(
            r'\s+',
            '',
            after[0].full_source).endswith(
            re.sub(
                r'\s+',
                '',
                new_funcs[0].full_source).lstrip('deftest_root_scalar_muller(self,somethingelse):'))

    def test_extend_mode_signature_mismatch_rejected(self):
        """
        Test merge_tests' "EXTEND" mode
        New test file contains a test class + test method that is mapped
        to an existing test method with a different signature

        The merge should be rejected
        """
        new_test_path = 'approach/utils/tests/new_test_6.py'
        existing_test_path = 'approach/utils/tests/existing_test_3.py'
        mapping_path = 'approach/utils/tests/mapping_2.json'

        # check there
        # 1) exists only one test class + test method
        with open(new_test_path, 'r') as f:
            new_test_code = f.read()
        new_funcs = extract_functions(new_test_code)
        assert_contains_function(
            new_funcs,
            'test_root_scalar_muller',
            class_name='Test_muller')

        # the list of funcs in the existing test file
        with open(existing_test_path, 'r') as f:
            existing_test_code = f.read()
        existing_funcs = extract_functions(existing_test_code)
        # check the existing test file contains the test method
        # test__muller_real_roots
        assert_contains_function(
            existing_funcs,
            'test__muller_real_roots',
            class_name='Test_muller')

        # mapping
        with open(mapping_path, 'r') as f:
            mapping = json.load(f)

        # Run merge_tests in EXTEND mode
        with pytest.raises(ValueError) as value_error:
            _, _ = merge_tests(
                new_src=new_test_code,
                base_src=existing_test_code,
                mode='APPEND',
                mapping=mapping
            )
        assert "Signatures differ for" in str(value_error.value) \
            and "['self', 'mismatched_arg'] vs ['self', 'somethingelse']" \
            in str(value_error.value)
