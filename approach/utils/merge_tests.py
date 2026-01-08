#!/usr/bin/env python
"""
merge_tests_cli.py
==================

Merge Python test files in three flexible modes:

* **ADD** – (default) copy new tests/imports/classes/functions into the target file if they don’t already exist.
* **APPEND** – append the *body* of a new function/method (from new_src) to an *existing* function/method (in existing_src) as designated in a mapping.
                Decorators from the new callable are added to the target if not already present.
                Raises ValueError if source and target callable signatures differ, or if target not found.
                Supports both top-level functions and class methods.
* **FOLD** – placeholder for future work (raises ``NotImplementedError`` for now).

Usage (examples)
----------------
```
# simple add
python merge_tests_cli.py NEW.py EXISTING.py

# append bodies using a JSON mapping file (methods and functions)
python merge_tests_cli.py NEW.py EXISTING.py --mode append \
    --map method_map.json -o merged.py -vv
```

A *mapping* file is only required for **APPEND** mode. It must be a JSON
object. For class methods, use `{"NewClass.new_method": "TargetClass.target_method"}`.
For top-level functions, use `{"new_function_name": "target_function_name"}`. E.g.::

    {
        "TestFoo.test_extra": "TestFoo.test_original",
        "OtherClass.test_new": "OtherClass.test_existing",
        "my_new_util_func": "my_existing_util_func"
    }

The script keeps formatting intact by splicing raw source segments rather
than re‑generating code from ASTs. Decorators are handled in both ADD and APPEND modes.
"""
from __future__ import annotations

import ast
import json
import logging
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Set
import textwrap
import re

import click
from approach.utils.test_extractor import ExtractedFunction

LOG = logging.getLogger("merge_tests")

###############################################################################
# ── helpers: generic ─────────────────────────────────────────────────────────
###############################################################################


def get_leading_whitespace(s: str) -> str:
    """Returns the leading whitespace of a string."""
    match = re.match(r"^(\s*)", s)
    return match.group(1) if match else ""


def _reindent(snippet: str, base_indent_str: str) -> str:
    """Dedent *snippet* completely, then indent each line with base_indent_str."""
    if base_indent_str.strip():
        LOG.warning(
            f"base_indent_str '{base_indent_str!r}' contains non-whitespace. Using no indent.")
        base_indent_str = ""

    dedented_lines = textwrap.dedent(snippet).splitlines()
    if not any(line.strip() for line in dedented_lines) and dedented_lines:
        return "\n" * len(dedented_lines)

    reindented_lines = [base_indent_str + line if line.strip() else line
                        for line in dedented_lines]

    result = "\n".join(reindented_lines)
    if result and not result.endswith("\n"):
        result += "\n"
    return result


def _index(tree: ast.Module):
    """Return sets/dicts of imports, classes, and top‑level functions."""
    imps = {ast.dump(n) for n in tree.body if isinstance(
        n, (ast.Import, ast.ImportFrom))}
    cls_map = {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}
    fn_map = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    return imps, cls_map, fn_map


def _splice(lines: List[str], pos_0based: int, payload: List[str]):
    """Splice payload into lines at pos_0based (0-based)."""
    actual_pos = max(0, min(pos_0based, len(lines)))
    if actual_pos != pos_0based:
        LOG.debug(
            f"Splice position {pos_0based} adjusted to {actual_pos} for lines length {len(lines)}")
    lines[actual_pos:actual_pos] = payload


def _last_import_line(tree: ast.Module) -> int:
    """Return the 1-based line number of the last import. 0 if no imports."""
    end = 0
    for n in tree.body:
        if isinstance(
                n, (ast.Import, ast.ImportFrom)) and n.end_lineno is not None:
            end = max(end, n.end_lineno)
    return end

# def _get_node_source_segment(src: str, node: ast.AST) -> str:
#     """
#     Return raw source snippet for the given AST node from the full source src.
#     Includes original indentation. For FunctionDef/ClassDef, includes decorators.
#     """
#     node_name = getattr(node, 'name', f"type {type(node).__name__}")

#     if isinstance(
#             node, (ast.FunctionDef, ast.ClassDef)) and node.decorator_list:
#         source_lines = src.splitlines(keepends=True)
#         first_decorator = node.decorator_list[0]
#         start_lineno = first_decorator.lineno
#         end_lineno = node.end_lineno

#         if start_lineno is None or end_lineno is None:
#             LOG.error(
#                 f"Cannot determine start/end lines for decorated node '{node_name}' line {getattr(node, 'lineno', 'N/A')}")
#             return ""

#         try:
#             segment = "".join(source_lines[start_lineno - 1: end_lineno])
#         except IndexError:
#             LOG.error(
#                 f"Line number out of bounds for decorated node '{node_name}'. Start: {start_lineno}, End: {end_lineno}, Lines: {len(source_lines)}")
#             return ""
#     else:
#         segment = ast.get_source_segment(src, node)

#     if segment is None:
#         LOG.error(
#             f"Could not extract source segment for node '{node_name}' at line {getattr(node, 'lineno', 'N/A')}")
#         return ""
#     return segment.rstrip()


def _get_node_source_segment_v2(src: str, node: ast.AST) -> str:
    """
    Return the source code snippet for the given AST node from the full source src.

    Common leading indentation is removed. For a FunctionDef or ClassDef,
    this includes any decorators.
    """
    node_name = getattr(node, 'name', f"type {type(node).__name__}")

    # Determine the start and end line numbers for the code segment.
    # For decorated nodes, the start line is the first decorator's line number.
    start_lineno = getattr(node, 'lineno', None)
    if isinstance(node, (ast.FunctionDef, ast.ClassDef)
                  ) and node.decorator_list:
        start_lineno = node.decorator_list[0].lineno

    end_lineno = getattr(node, 'end_lineno', None)

    if start_lineno is None or end_lineno is None:
        LOG.error(
            f"Cannot determine start/end lines for node '{node_name}' "
            f"at line {getattr(node, 'lineno', 'N/A')}")
        return ""

    # Extract the segment from the source using line numbers, which is more reliable
    # than ast.get_source_segment for indented code blocks like methods.
    source_lines = src.splitlines(keepends=True)
    try:
        segment = "".join(source_lines[start_lineno - 1:end_lineno])
    except IndexError:
        LOG.error(
            f"Line number out of bounds for node '{node_name}'. "
            f"Start: {start_lineno}, End: {end_lineno}, Lines: {len(source_lines)}")
        return ""

    if not segment:
        LOG.error(
            f"Could not extract source segment for node '{node_name}' "
            f"at line {getattr(node, 'lineno', 'N/A')}")
        return ""

    # remove the trailing newlines if they exist
    return segment.rstrip()

###############################################################################
# ── core merge operations ───────────────────────────────────────────────────
###############################################################################


class Merger:
    def __init__(self, base_src: str):
        self.lines: List[str] = base_src.splitlines(keepends=True)
        if self.lines and self.lines[-1] and not self.lines[-1].endswith("\n"):
            self.lines[-1] = self.lines[-1].rstrip('\r\n') + '\n'
        elif not self.lines and base_src.strip():
            self.lines = [base_src.rstrip('\r\n') + '\n']
        elif not self.lines and not base_src.strip():  # Empty base_src
            self.lines = []

        self.tree: ast.Module
        self.cls_map: Dict[str, ast.ClassDef]
        self.fn_map: Dict[str, ast.FunctionDef]
        self._refresh_index()

    def _signatures_match(self, sig1: ast.arguments,
                          sig2: ast.arguments) -> Tuple[bool, str]:
        s1_posonly = [a.arg for a in sig1.posonlyargs]
        s2_posonly = [a.arg for a in sig2.posonlyargs]
        if s1_posonly != s2_posonly:
            return False, f"Positional-only arguments differ: {s1_posonly} vs {s2_posonly}"
        s1_args = [a.arg for a in sig1.args]
        s2_args = [a.arg for a in sig2.args]
        if s1_args != s2_args:
            return False, f"Positional arguments differ: {s1_args} vs {s2_args}"
        s1_vararg = sig1.vararg.arg if sig1.vararg else None
        s2_vararg = sig2.vararg.arg if sig2.vararg else None
        if s1_vararg != s2_vararg:
            return False, f"*args differ: '{s1_vararg}' vs '{s2_vararg}'"
        s1_kwonly = [a.arg for a in sig1.kwonlyargs]
        s2_kwonly = [a.arg for a in sig2.kwonlyargs]
        if s1_kwonly != s2_kwonly:
            return False, f"Keyword-only arguments differ: {s1_kwonly} vs {s2_kwonly}"
        s1_kwarg = sig1.kwarg.arg if sig1.kwarg else None
        s2_kwarg = sig2.kwarg.arg if sig2.kwarg else None
        if s1_kwarg != s2_kwarg:
            return False, f"**kwargs differ: '{s1_kwarg}' vs '{s2_kwarg}'"
        return True, ""

    def add_imports(self, imports: List[str]):
        if not imports:
            return
        splice_pos_0based = _last_import_line(self.tree)
        _splice(self.lines, splice_pos_0based, imports)
        self._refresh_index()

    def add_class_or_func(self, snippet: str):
        # Ensure snippet itself ends with a newline if it's not just whitespace
        clean_snippet = snippet
        if clean_snippet.strip() and not clean_snippet.endswith("\n"):
            clean_snippet = clean_snippet.rstrip('\r\n') + '\n'

        prefix = "\n"
        if not self.lines or self.lines[-1].strip(
        ) == "" or self.lines[-1].endswith("\n\n"):
            prefix = ""
        # Last line has content but no newline
        elif not self.lines[-1].endswith("\n"):
            self.lines[-1] = self.lines[-1].rstrip('\r\n') + '\n'
            # prefix remains "\n" to ensure a blank line separator

        _splice(self.lines, len(self.lines), [prefix + clean_snippet])
        self._refresh_index()

    def add_methods(self, class_name: str, methods: List[str]):
        if class_name not in self.cls_map:
            LOG.error(f"Class {class_name} not found. Cannot add methods.")
            return
        cls_node = self.cls_map[class_name]
        if cls_node.end_lineno is None:
            LOG.error(
                f"Class {class_name} has no end_lineno. Cannot add methods.")
            return

        insertion_idx_0based: int
        if cls_node.body:
            last_member = cls_node.body[-1]
            if last_member.end_lineno is None:
                LOG.error(
                    f"Last member of class {class_name} has no end_lineno. Cannot reliably add methods.")
                return
            insertion_idx_0based = last_member.end_lineno
        else:
            insertion_idx_0based = cls_node.lineno

        class_def_line_idx_0based = cls_node.lineno - 1
        class_indent_str = ""
        if 0 <= class_def_line_idx_0based < len(self.lines):
            class_indent_str = get_leading_whitespace(
                self.lines[class_def_line_idx_0based])

        method_indent_str = class_indent_str + ("    "
                                                if "\t"
                                                not in class_indent_str else
                                                "\t")

        payload: List[str] = []
        prev_line_idx_0based = insertion_idx_0based - 1
        if prev_line_idx_0based >= 0 and prev_line_idx_0based < len(
                self.lines):
            current_prev_line = self.lines[prev_line_idx_0based]
            if current_prev_line.strip() and not current_prev_line.endswith("\n"):
                self.lines[prev_line_idx_0based] = current_prev_line.rstrip(
                    '\r\n') + '\n'
                # Needs a blank line after fixing previous
                payload.append("\n")
            elif current_prev_line.strip():
                payload.append("\n")  # Needs a blank line
        elif self.lines:
            # Default separation if inserting not at beginning
            payload.append("\n")

        payload.extend([_reindent(snip, method_indent_str)
                       for snip in methods])
        _splice(self.lines, insertion_idx_0based, payload)
        self._refresh_index()

    def append_callable_body(
            self, target_name: str, new_callable_snippet: str,
            target_cls_name: Optional[str] = None) -> None:
        target_callable_node: ast.FunctionDef
        is_method = target_cls_name is not None

        if is_method:
            if target_cls_name not in self.cls_map:
                raise ValueError(
                    f"Target class '{target_cls_name}' not found.")
            target_cls_node = self.cls_map[target_cls_name]
            try:
                target_callable_node = next(
                    m for m in target_cls_node.body if isinstance(
                        m, ast.FunctionDef) and m.name == target_name)
            except StopIteration:
                raise ValueError(
                    f"Target method '{target_cls_name}.{target_name}' not found.")
        else:
            if target_name not in self.fn_map:
                raise ValueError(f"Target function '{target_name}' not found.")
            target_callable_node = self.fn_map[target_name]

        if target_callable_node.lineno is None:
            raise ValueError(f"Target callable '{target_name}' has no lineno.")

        dedented_new_snippet_str = textwrap.dedent(new_callable_snippet)
        try:
            new_callable_ast_root = ast.parse(dedented_new_snippet_str)
        except SyntaxError as e:
            raise ValueError(
                f"Syntax error in new snippet for '{target_name}': {e}")
        if not new_callable_ast_root.body or not isinstance(
                new_callable_ast_root.body[0],
                ast.FunctionDef):
            raise ValueError(
                f"New snippet for '{target_name}' not a function def.")
        parsed_new_callable_node = new_callable_ast_root.body[0]

        signatures_match, reason = self._signatures_match(
            parsed_new_callable_node.args, target_callable_node.args)
        if not signatures_match:
            raise ValueError(
                f"Signatures differ for '{target_name}': {reason}")

        decorator_splice_idx_0based = target_callable_node.lineno - 1

        if not (0 <= decorator_splice_idx_0based < len(self.lines)):
            raise ValueError(
                f"Target '{target_name}' lineno {target_callable_node.lineno} out of bounds for file len {len(self.lines)}.")

        line_content_at_splice_idx = self.lines[decorator_splice_idx_0based]
        stripped_line_content = line_content_at_splice_idx.lstrip()
        if not (stripped_line_content.startswith("def ")
                or stripped_line_content.startswith("@")):
            err_msg = (
                f"AST lineno for target callable '{target_name}' seems incorrect. " f"Expected 'def' or '@' at line {target_callable_node.lineno} (0-idx {decorator_splice_idx_0based}), " f"but found: '{line_content_at_splice_idx.strip()}'. " f"Node details: lineno={target_callable_node.lineno}, end_lineno={target_callable_node.end_lineno}, col_offset={target_callable_node.col_offset}.")
            LOG.error(err_msg)
            raise ValueError(
                f"AST lineno for '{target_name}' (line {target_callable_node.lineno}) does not point to its definition. Cannot reliably insert decorators.")

        actual_target_indent_str = get_leading_whitespace(
            line_content_at_splice_idx)
        target_deco_src_stripped = {
            _get_node_source_segment_v2(
                "".join(self.lines),
                d).strip()
            for d in
            target_callable_node.decorator_list}
        new_decos_payload: List[str] = []
        for deco_node in parsed_new_callable_node.decorator_list:
            deco_expr_src = _get_node_source_segment_v2(
                dedented_new_snippet_str, deco_node)
            if not deco_expr_src:
                continue
            if deco_expr_src.strip() not in target_deco_src_stripped:
                deco_lines = deco_expr_src.splitlines()
                first_deco_line_text = deco_lines[0].lstrip(
                ) if deco_lines else ""
                reconstructed_deco = [
                    f"{actual_target_indent_str}{first_deco_line_text}"]
                # For multi-line decorators, subsequent lines should align with
                # the indent of the @ line.
                reconstructed_deco.extend(
                    [f"{actual_target_indent_str}{line.lstrip()}"
                     for line in deco_lines[1:]])
                new_decos_payload.append("\n".join(reconstructed_deco) + "\n")

        if new_decos_payload:
            _splice(self.lines, decorator_splice_idx_0based, new_decos_payload)
            self._refresh_index()
            if is_method:
                target_cls_node = self.cls_map.get(target_cls_name)
                if not target_cls_node:
                    raise ValueError(
                        f"Target class '{target_cls_name}' missing after deco update.")
                try:
                    target_callable_node = next(
                        m for m in target_cls_node.body
                        if isinstance(m, ast.FunctionDef) and m.name
                        == target_name)
                except StopIteration:
                    raise ValueError(
                        f"Target method '{target_name}' missing after deco update.")
            else:
                target_callable_node = self.fn_map.get(target_name)
                if not target_callable_node:
                    raise ValueError(
                        f"Target function '{target_name}' missing after deco update.")
            if target_callable_node.lineno is None:
                raise ValueError(
                    f"Target '{target_name}' lineno lost after deco update.")

        body_lines_new: List[str] = []
        if parsed_new_callable_node.body:
            first_stmt = parsed_new_callable_node.body[0]
            last_stmt = parsed_new_callable_node.body[-1]
            if first_stmt.lineno is not None and last_stmt.end_lineno is not None:
                all_dedented_lines = dedented_new_snippet_str.splitlines(
                    keepends=True)
                body_lines_new = all_dedented_lines[first_stmt.lineno -
                                                    1: last_stmt.end_lineno]

        body_to_append_str = "".join(body_lines_new)
        if not body_to_append_str.strip():
            LOG.debug(f"No body content from new snippet for '{target_name}'.")
            return

        body_splice_idx_0based: int
        body_indent_str: str
        if target_callable_node.body:
            last_target_stmt = target_callable_node.body[-1]
            if last_target_stmt.end_lineno is None:
                raise ValueError("Target's last stmt has no end_lineno.")
            body_splice_idx_0based = last_target_stmt.end_lineno

            first_target_stmt_line_idx_0based = target_callable_node.body[0].lineno - 1
            if 0 <= first_target_stmt_line_idx_0based < len(self.lines):
                body_indent_str = get_leading_whitespace(
                    self.lines[first_target_stmt_line_idx_0based])
                if not body_indent_str and self.lines[first_target_stmt_line_idx_0based].strip(
                ):
                    def_idx_0based = target_callable_node.lineno - 1
                    def_indent = get_leading_whitespace(
                        self.lines[def_idx_0based]) if 0 <= def_idx_0based < len(
                        self.lines) else ""
                    body_indent_str = def_indent + \
                        ("    " if "\t" not in def_indent else "\t")
            else:
                def_idx_0based = target_callable_node.lineno - 1
                def_indent = get_leading_whitespace(
                    self.lines[def_idx_0based]) if 0 <= def_idx_0based < len(
                    self.lines) else ""
                body_indent_str = def_indent + ("    "
                                                if "\t" not in def_indent else
                                                "\t")
        else:
            body_splice_idx_0based = target_callable_node.lineno
            def_idx_0based = target_callable_node.lineno - 1
            def_indent_str = get_leading_whitespace(
                self.lines[def_idx_0based]) if 0 <= def_idx_0based < len(
                self.lines) else ""
            body_indent_str = def_indent_str + \
                ("    " if "\t" not in def_indent_str else "\t")

        reindented_body = _reindent(body_to_append_str, body_indent_str)

        prefix_for_body = "\n"
        prev_body_splice_line_idx_0based = body_splice_idx_0based - 1
        if prev_body_splice_line_idx_0based >= 0 and prev_body_splice_line_idx_0based < len(
                self.lines):
            current_prev_line = self.lines[prev_body_splice_line_idx_0based]
            if not current_prev_line.strip():
                prefix_for_body = ""
            elif not current_prev_line.endswith("\n"):
                self.lines[prev_body_splice_line_idx_0based] = current_prev_line.rstrip(
                    '\r\n') + '\n'

        _splice(self.lines, body_splice_idx_0based,
                [prefix_for_body + reindented_body])
        self._refresh_index()

    def result(self) -> str:
        return "".join(self.lines)

    def _refresh_index(self):
        current_source = "".join(self.lines)
        if not current_source.strip():
            self.tree = ast.Module(body=[], type_ignores=[])
            self.cls_map = {}
            self.fn_map = {}
            return
        # Ensure source ends with a newline for parser stability
        if not current_source.endswith("\n"):
            current_source = current_source.rstrip('\r\n') + '\n'

        # Defensive: Ensure all lines in self.lines end with a newline before joining
        # This is a bit heavy-handed but can prevent subtle issues.
        processed_lines = []
        for line_idx, line_content in enumerate(self.lines):
            if line_content.strip() and not line_content.endswith("\n"):
                # LOG.debug(f"Line {line_idx+1} (0-idx {line_idx}) was missing newline: {line_content!r}")
                processed_lines.append(line_content.rstrip('\r\n') + '\n')
            else:
                processed_lines.append(line_content)
        current_source = "".join(processed_lines)
        # Final check
        if not current_source.endswith("\n") and current_source.strip():
            current_source += "\n"

        try:
            self.tree = ast.parse(current_source)
            _, self.cls_map, self.fn_map = _index(self.tree)
            self.lines = current_source.splitlines(keepends=True)
        except SyntaxError as e:
            LOG.error(
                f"Syntax error while re-parsing source after modification: {e}")
            # LOG.debug(f"Problematic source for _refresh_index ({len(current_source.splitlines())} lines):\n---\n{current_source}\n---")
            raise

###############################################################################
# ── high‑level merge orchestrator ───────────────────────────────────────────
###############################################################################


def merge_tests(new_src: str,
                base_src: str,
                mode: str = "ADD",
                mapping: Dict[str,
                              str] | None = None) -> Tuple[str,
                                                           Set[ExtractedFunction]]:
    mode = mode.upper()
    merger = Merger(base_src)
    # The test functions that are merged into
    merged_test_funcs: Set[ExtractedFunction] = set()

    try:
        new_tree = ast.parse(new_src)
    except SyntaxError as e:
        raise ValueError(f"Invalid syntax in new_src: {e}") from e

    base_imps_dump_initial = {
        ast.dump(n) for n in merger.tree.body
        if isinstance(n, (ast.Import, ast.ImportFrom))}
    new_imports_to_add: List[str] = []
    pending_methods_for_add: Dict[str, List[Tuple[str, str]]] = {}
    pending_methods_for_append: Dict[str, List[Tuple[str, str]]] = {}
    pending_functions_for_append: Dict[str, str] = {}

    for node in new_tree.body:
        node_full_snippet = _get_node_source_segment_v2(new_src, node)
        if not node_full_snippet:
            continue

        # Ensure snippet ends with a newline if it contains code
        if node_full_snippet.strip() and not node_full_snippet.endswith("\n"):
            node_full_snippet = node_full_snippet.rstrip('\r\n') + '\n'

        if isinstance(node, (ast.Import, ast.ImportFrom)):
            # Import snippets from _get_node_source_segment should already have
            # their own newlines if from source.
            if ast.dump(node) not in base_imps_dump_initial:
                new_imports_to_add.append(node_full_snippet)
                base_imps_dump_initial.add(ast.dump(node))
            continue

        if isinstance(node, ast.ClassDef):
            methods_in_new_class = []
            for m_node in node.body:
                if isinstance(m_node, ast.FunctionDef):
                    method_snippet = _get_node_source_segment_v2(
                        new_src, m_node)
                    if method_snippet:
                        if method_snippet.strip() and not method_snippet.endswith("\n"):
                            method_snippet = method_snippet.rstrip(
                                '\r\n') + '\n'
                        methods_in_new_class.append(
                            (m_node, method_snippet))

            if mode == "ADD":
                if node.name not in merger.cls_map:
                    merger.add_class_or_func(node_full_snippet)
                    # add all methods in this class to merged_test_funcs
                    merged_test_funcs.update([
                        ExtractedFunction(
                            class_name=node.name,
                            func_name=m_node.name,
                            func_def=method_snippet)
                        for m_node, method_snippet
                        in methods_in_new_class
                        if m_node.name.startswith("test_")])
                else:
                    pending_methods_for_add.setdefault(
                        node.name, []).extend(methods_in_new_class)
            elif mode == "APPEND":
                pending_methods_for_append.setdefault(
                    node.name, []).extend(methods_in_new_class)

        elif isinstance(node, ast.FunctionDef):
            if mode == "ADD":
                if node.name not in merger.fn_map:
                    merger.add_class_or_func(node_full_snippet)
                    merged_test_funcs.add(ExtractedFunction(
                        class_name=None,
                        func_name=node.name,
                        func_def=node_full_snippet))
            elif mode == "APPEND":
                pending_functions_for_append[node.name] = node_full_snippet

    if new_imports_to_add:
        merger.add_imports(new_imports_to_add)

    if mode == "ADD":
        for cls_name, new_methods in pending_methods_for_add.items():
            if cls_name in merger.cls_map:
                existing_meth_names = {m.name
                                       for m in merger.cls_map[cls_name].body
                                       if isinstance(m, ast.FunctionDef)}
                to_add_snippets = [
                    s for name, s in new_methods
                    if name not in existing_meth_names]
                if to_add_snippets:
                    merger.add_methods(cls_name, to_add_snippets)
                    merged_test_funcs.update(
                        ExtractedFunction(
                            class_name=cls_name,
                            func_name=name,
                            func_def=method_snippet)
                        for name,
                        method_snippet in new_methods
                        if name not in
                        existing_meth_names)

    elif mode == "APPEND":
        if not mapping:
            raise ValueError("--map is required in APPEND mode.")
        for src_cls, meth_list in pending_methods_for_append.items():
            for src_meth, new_snip in meth_list:
                fq_new = f"{src_cls}.{src_meth.name}"
                if fq_new not in mapping:
                    LOG.warning(f"No map for method '{fq_new}'. Skip.")
                    continue
                target_fq = mapping[fq_new]
                try:
                    tgt_cls, tgt_meth = target_fq.split(".", 1)
                    if not tgt_cls or not tgt_meth:
                        raise ValueError("Bad format")
                except ValueError:
                    LOG.warning(
                        f"Target '{target_fq}' for '{fq_new}' not 'Cls.meth'. Skip.")
                    continue
                try:
                    merger.append_callable_body(tgt_meth, new_snip, tgt_cls)
                    merged_test_funcs.add(ExtractedFunction(
                        class_name=tgt_cls,
                        func_name=tgt_meth,
                        func_def=None))
                except ValueError as e:
                    LOG.error(f"Fail append {fq_new} to {target_fq}: {e}")
                    raise

        for src_func, new_snip in pending_functions_for_append.items():
            if src_func not in mapping:
                LOG.warning(f"No map for func '{src_func}'. Skip.")
                continue
            target_func = mapping[src_func]
            if "." in target_func:
                LOG.warning(
                    f"Map for func '{src_func}' -> '{target_func}' (method?). Skip.")
                continue
            try:
                merger.append_callable_body(target_func, new_snip)
                merged_test_funcs.add(ExtractedFunction(
                    class_name=None,
                    func_name=target_func,
                    func_def=None))
            except ValueError as e:
                LOG.error(
                    f"Fail append func '{src_func}' to '{target_func}': {e}")
                raise

    elif mode == "FOLD":
        raise NotImplementedError("FOLD mode not implemented yet")
    else:
        raise ValueError(f"Unknown test merge mode: {mode}")
    return merger.result(), merged_test_funcs

###############################################################################
# ── CLI ─────────────────────────────────────────────────────────────────────
###############################################################################


@click.command()
@click.argument(
    "test_input", type=click.Path(
        exists=True, readable=True, dir_okay=False, path_type=Path))
@click.argument(
    "test_existing", type=click.Path(
        exists=True, readable=True, dir_okay=False, path_type=Path))
@click.option("--mode", type=click.Choice(
    ["ADD", "APPEND", "FOLD"],
    case_sensitive=False),
    default="ADD", show_default=True, help="Merge mode.")
@click.option("--map", "map_file", type=click.Path(
    exists=True, readable=True, dir_okay=False, path_type=Path),
    help="JSON mapping file (required for APPEND mode). Format: {'New.callable': 'Target.callable'}")
@click.option("-o", "--output", type=click.Path(
    writable=True, dir_okay=False, path_type=Path),
    help="Output file path. If not provided, 'test_existing' file is overwritten.")
@click.option("-v", "--verbose", count=True,
              help="Increase verbosity (e.g., -v for INFO, -vv for DEBUG).")
@click.option("--debug/--no-debug", default=False, show_default=True,
              help="Enable debug logging (overrides verbosity).")
@click.option("--dry-run", is_flag=True,
              help="Print merged output to stdout instead of writing to file.")
def cli(
        test_input: Path,
        test_existing: Path,
        mode: str,
        map_file: Path | None,
        output: Path | None,
        verbose: int,
        debug: bool,
        dry_run: bool):
    log_level = logging.WARNING
    if verbose == 1:
        log_level = logging.INFO
    elif verbose >= 2:
        log_level = logging.DEBUG
    if debug:
        log_level = logging.DEBUG
    logging.basicConfig(
        level=log_level, format="%(levelname)s (%(name)s): %(message)s")
    LOG.setLevel(log_level)
    LOG.info(
        f"Starting merge: input='{test_input}', existing='{test_existing}', mode='{mode.upper()}'")
    if map_file:
        LOG.info(f"Mapping file: {map_file}")

    mapping_data: Dict[str, str] | None = None
    if mode.upper() == "APPEND":
        if not map_file:
            raise click.ClickException(
                "ERROR: --map option is required for APPEND mode.")
        try:
            mapping_data = json.loads(map_file.read_text())
            if not isinstance(mapping_data, dict):
                raise click.ClickException(
                    f"ERROR: Map file {map_file} not a JSON object.")
            LOG.info(f"Loaded map file with {len(mapping_data)} entries.")
        except json.JSONDecodeError as e:
            raise click.ClickException(
                f"ERROR: Invalid JSON in map file {map_file}: {e}")
        except Exception as e:
            raise click.ClickException(
                f"ERROR: Could not read/parse map file {map_file}: {e}")
    try:
        input_src = test_input.read_text()
        existing_src = test_existing.read_text()
    except Exception as e:
        raise click.ClickException(f"Error reading input files: {e}")
    try:
        merged_code, merged_test_funcs = merge_tests(
            new_src=input_src, base_src=existing_src, mode=mode,
            mapping=mapping_data)
    except NotImplementedError as e:
        raise click.ClickException(f"ERROR: {e}")
    except ValueError as e:
        raise click.ClickException(f"ERROR during merge: {e}")
    except Exception as e:
        LOG.exception("Unexpected error during merge.")
        raise click.ClickException(
            f"Unexpected critical error: {e}. Check logs.")
    if dry_run:
        click.echo(merged_code)
    else:
        output_path = output if output else test_existing
        try:
            output_path.write_text(merged_code)
            click.secho(
                f"Successfully merged into test functions: {merged_test_funcs}",
                fg="green")
            click.secho(
                f"Successfully merged. Output: {output_path}", fg="green")

        except Exception as e:
            raise click.ClickException(
                f"Error writing output to {output_path}: {e}")


if __name__ == "__main__":
    cli()
