import os
import re
from typing import Dict, List, Union


class GrepSearch:
    def __init__(self, root_dir: str = "."):
        self.messages: List[Dict[str, str]] = []
        self.root_dir = root_dir

    def add_message(self, message: Dict[str, str]):
        self.messages.append(message)

    def search(
        self,
        patterns: Union[str, List[str]],
        k: int = 5,
        case_sensitive: bool = False,
        search_files: bool = True,
        context_lines: int = 2,
    ) -> List[Dict[str, str]]:
        if isinstance(patterns, str):
            patterns = [patterns]

        flags = 0 if case_sensitive else re.IGNORECASE
        regexes = [re.compile(pattern, flags) for pattern in patterns]

        matches = []

        # Search messages
        for msg in self.messages:
            for regex in regexes:
                for match in regex.finditer(msg["content"]):
                    start = max(0, match.start() - 100)
                    end = min(len(msg["content"]), match.end() + 100)
                    matches.append(
                        {
                            "type": "message",
                            "content": msg["content"][start:end],
                            "context": msg["content"][start:end],
                            "match": match.group(),
                        }
                    )

        # Search files
        if search_files:
            for root, _, files in os.walk(self.root_dir):
                # Skip __pycache__, penguin_venv, and .env directories
                if any(
                    excluded in root
                    for excluded in ["__pycache__", "penguin_venv", ".env"]
                ):
                    continue
                for file in files:
                    if file.endswith(
                        (".md", ".txt", ".py")
                    ):  # Add more file types if needed
                        file_path = os.path.join(root, file)
                        try:
                            with open(file_path, encoding="utf-8") as f:
                                lines = f.readlines()
                                for i, line in enumerate(lines):
                                    for regex in regexes:
                                        if regex.search(line):
                                            start = max(0, i - context_lines)
                                            end = min(len(lines), i + context_lines + 1)
                                            context = "".join(lines[start:end])
                                            matches.append(
                                                {
                                                    "type": "file",
                                                    "path": file_path,
                                                    "content": context,
                                                    "context": context,
                                                    "match": line.strip(),
                                                }
                                            )
                        except Exception as e:
                            print(f"Error reading file {file_path}: {str(e)}")

        # Sort matches by relevance (you might want to implement a more sophisticated sorting method)
        # For now, we'll just put file matches first, then message matches
        sorted_matches = sorted(matches, key=lambda x: x["type"])

        return sorted_matches[:k]  # Return only the top k matches

        # Sort matches by relevance (you might want to implement a more sophisticated sorting method)
        # For now, we'll just put file matches first, then message matches
        sorted_matches = sorted(matches, key=lambda x: x["type"])

        return sorted_matches[:k]  # Return only the top k matches
