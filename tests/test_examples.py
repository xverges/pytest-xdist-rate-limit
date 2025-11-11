"""Auto-generated tests from examples folder.

Tests are generated from TEST_CODE sections in example file docstrings.
If no TEST_CODE is found, a failing test is created.

Example TEST_CODE in docstring:
    TEST_CODE:
    ```python
    result = pytester.runpytest('--load-test', '-n', '2', '-v')
    result.stdout.fnmatch_lines([
        '*Interrupted: Example completed after * iterations*',
    ])
    assert result.ret == pytest.ExitCode.INTERRUPTED
    ```
"""

import textwrap
from pathlib import Path

import pytest

# Get the examples directory
EXAMPLES_DIR = Path(__file__).parent.parent / "examples"


def extract_test_code(file_path):
    """Extract TEST_CODE section from file docstring.

    Returns the test code as a string, or None if not found.
    """
    with open(file_path, "r") as f:
        content = f.read()

    # Look for TEST_CODE marker in docstring
    if "TEST_CODE:" not in content:
        return None

    # Find the docstring
    lines = content.split("\n")
    in_docstring = False
    in_test_code = False
    in_code_block = False
    test_code_lines = []
    found_code = False

    for line in lines:
        stripped = line.strip()

        # Track docstring boundaries
        if '"""' in line:
            in_docstring = not in_docstring
            # If we found code and exited docstring, we're done
            if not in_docstring and found_code:
                break
            continue

        if not in_docstring:
            continue

        # Look for TEST_CODE marker
        if "TEST_CODE:" in stripped:
            in_test_code = True
            continue

        if in_test_code:
            # Check for code block markers
            if "```python" in stripped or "```" in stripped:
                in_code_block = not in_code_block
                # If we just closed the code block, we're done
                if not in_code_block and test_code_lines:
                    found_code = True
                    break
                continue

            # Collect code lines
            if in_code_block:
                test_code_lines.append(line)
            elif stripped and not stripped.startswith("```"):
                # Also accept non-fenced code (indented)
                test_code_lines.append(line)

    if not test_code_lines:
        return None

    # Dedent the code
    code = "\n".join(test_code_lines)
    return textwrap.dedent(code).strip()


def get_example_files():
    """Get all test files from examples directory."""
    if not EXAMPLES_DIR.exists():
        return []

    files = []
    for file in EXAMPLES_DIR.glob("test_*.py"):
        if file.name != "__init__.py":
            files.append(file)
    return sorted(files)


def generate_test_function(example_file):
    """Generate a test function for an example file."""
    file_name = example_file.name
    test_name = f"test_{example_file.stem}_auto"

    test_code = extract_test_code(example_file)

    if test_code is None:
        # No test code found - create failing test
        def test_missing_code(pytester, run_with_timeout):
            pytest.fail(
                f"No TEST_CODE found in {file_name}. Add TEST_CODE section to docstring with test implementation."
            )

        test_missing_code.__name__ = test_name
        test_missing_code.__doc__ = f"MISSING TEST_CODE: {file_name}"
        return test_missing_code

    # Create test function that executes the test code
    def test_from_code(pytester, run_with_timeout):
        # Copy example and conftest
        pytester.copy_example(f"examples/{file_name}")
        pytester.copy_example("examples/conftest.py")

        # Execute the test code
        exec(test_code, {"pytester": pytester, "pytest": pytest, "run_with_timeout": run_with_timeout})

    test_from_code.__name__ = test_name
    test_from_code.__doc__ = f"Auto-generated test for {file_name}"
    return test_from_code


# Generate tests for all example files
_example_files = get_example_files()
if _example_files:
    for _example_file in _example_files:
        _test_func = generate_test_function(_example_file)
        # Add to module globals so pytest discovers it
        globals()[_test_func.__name__] = _test_func
