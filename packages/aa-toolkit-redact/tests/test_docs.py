"""The code examples in the redaction library's README."""

import re
import subprocess
import sys


def test_every_example_in_the_readme_prints_what_the_readme_says(package_dir):
    readme = (package_dir / "README.md").read_text(encoding="utf-8")
    examples = re.findall(r"```python\n(.*?)```\n\n.*?\n\n```text\n(.*?)```", readme, re.DOTALL)
    assert len(examples) == readme.count("```python") >= 4

    for code, printed in examples:
        done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)

        assert done.stderr == ""
        assert done.stdout == printed
