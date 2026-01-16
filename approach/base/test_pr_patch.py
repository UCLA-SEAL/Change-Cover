import pytest
import shutil
from pathlib import Path
from approach.base.pr_patch import PRPatch


@pytest.fixture
def patch_instance():
    base_dir = Path('data/ci_testing/qiskit')
    if base_dir.exists():
        shutil.rmtree(base_dir)
    return PRPatch(
        repo_owner='Qiskit',
        repo_name='qiskit',
        pr_number=13652,
        base_dir='data/ci_testing/qiskit'
    )


def test_init_directories(patch_instance):
    """Test that directories are created during initialization."""
    patch_instance._ensure_directories_exist()
    assert patch_instance.base_dir.exists(), "Base directory not created."


def test_diff_file_retrieval(patch_instance):
    """Test that the diff file is retrieved and saved."""
    patch_instance.retrieve_diff_file()
    assert patch_instance.diff_path.exists(), "Diff file not saved."


def test_file_list_before(patch_instance):
    assert patch_instance.file_list_before == [
        'test/python/transpiler/test_preset_passmanagers.py'], "Before file list incorrect."


def test_iterate_file_contents_before(patch_instance):
    patch_instance.download_all_file_contents()
    for file_content in patch_instance.file_contents_before:
        assert 'file_path' in file_content, "File path missing."
        assert 'content' in file_content, "Content missing."
        assert file_content['file_path'] == 'test/python/transpiler/test_preset_passmanagers.py', "File path incorrect."
        assert file_content['content'], "Content missing."


def test_has_only_deletion_changes_on_these_files(patch_instance):
    """Test detection of deletion-only changes on specified files."""
    # Mock file_changes data
    mock_file_changes = [
        {
            "path": "deleted_file1.txt",
            "change_type": "DELETED",
            "base_content": None,
            "head_content": None
        },
        {
            "path": "deleted_file2.py",
            "change_type": "DELETED",
            "base_content": None,
            "head_content": None
        },
        {
            "path": "modified_file.py",
            "change_type": "MODIFIED",
            "base_content": "old content",
            "head_content": "new content"
        }
    ]

    # Mock the file_changes property
    patch_instance._mock_file_changes = mock_file_changes
    original_file_changes = patch_instance.file_changes
    patch_instance.__class__.file_changes = property(
        lambda self: self._mock_file_changes)

    try:
        # Test with files that are all deleted
        deleted_files = ["deleted_file1.txt", "deleted_file2.py"]
        result = patch_instance.has_only_deletion_changes_on_these_files(
            deleted_files)
        assert result is True, "Should return True for files that are all deleted"

        # Test with mixed changes (deleted and modified)
        mixed_files = ["deleted_file1.txt", "modified_file.py"]
        result = patch_instance.has_only_deletion_changes_on_these_files(
            mixed_files)
        assert result is False, "Should return False for files with mixed changes"

        # Test with only modified files
        modified_files = ["modified_file.py"]
        result = patch_instance.has_only_deletion_changes_on_these_files(
            modified_files)
        assert result is False, "Should return False for files that are not deleted"

        # Test with empty file list
        empty_files = []
        result = patch_instance.has_only_deletion_changes_on_these_files(
            empty_files)
        assert result is True, "Should return True for empty file list"

    finally:
        # Restore original property
        patch_instance.__class__.file_changes = original_file_changes
