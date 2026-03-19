import ast
import re

class SafetyChecker:
    DANGEROUS_PATTERNS = [
        r"\beval\s*\(",
        r"\bexec\s*\(",
        r"\b__import__\s*\(",
        r"\bcompile\s*\(",
        r"\bos\.system\s*\(",
        r"\bsubprocess\.(run|Popen|call|check_output|check_call)\s*\(",
    ]

    def check(self, code: str, file_path: str = "") -> tuple:
        issues = []

        for pattern in self.DANGEROUS_PATTERNS:
            if re.search(pattern, code):
                issues.append(f"Found dangerous pattern: {pattern}")

        # NOTE: We intentionally do NOT run ast.parse here.
        # The code passed to check() is a SNIPPET, not a full file.
        # A full-file syntax check runs later in patch_code.py step ④
        # after the snippet is inserted into the full file context.

        return len(issues) == 0, issues