"""
GitHub Diff Parser for CodeSage
"""
from dataclasses import dataclass
from typing import List, Optional
import re


@dataclass
class FileDiff:
    """Represents changes to a single file."""
    filename: str
    status: str  # added, modified, deleted, renamed
    additions: int = 0
    deletions: int = 0
    patch: str = ""
    old_path: Optional[str] = None
    new_path: Optional[str] = None
    language: Optional[str] = None


class DiffParser:
    """Parse GitHub-style diffs into structured data."""
    
    # Language detection by file extension
    LANGUAGE_MAP = {
        ".py": "python",
        ".js": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".jsx": "javascript",
        ".go": "go",
        ".rs": "rust",
        ".java": "java",
        ".rb": "ruby",
        ".php": "php",
        ".cs": "csharp",
        ".cpp": "cpp",
        ".c": "c",
        ".h": "c",
        ".hpp": "cpp",
        ".swift": "swift",
        ".kt": "kotlin",
        ".scala": "scala",
        ".md": "markdown",
        ".json": "json",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".sql": "sql",
        ".sh": "shell",
        ".bash": "bash",
        ".dockerfile": "dockerfile",
        ".tf": "terraform",
    }
    
    def __init__(self, max_chunk_size: int = 30 * 1024):
        self.max_chunk_size = max_chunk_size
    
    def parse(self, diff_text: str) -> List[FileDiff]:
        """Parse a complete diff into file changes."""
        files = []
        
        # Split by diff headers
        positions = [m.start() for m in re.finditer(r'diff --git ', diff_text)]
        positions.append(len(diff_text))
        
        for i in range(len(positions) - 1):
            file_diff_text = diff_text[positions[i]:positions[i + 1]]
            file_diff = self._parse_single_file(file_diff_text)
            if file_diff:
                files.append(file_diff)
        
        return files
    
    def _parse_single_file(self, text: str) -> Optional[FileDiff]:
        """Parse a single file's diff."""
        # Extract filename
        header_match = re.match(r'diff --git a/(.*?) b/(.*?)(?:\n|$)', text)
        if not header_match:
            return None
        
        old_path = header_match.group(1)
        new_path = header_match.group(2)
        
        # Determine status
        if text.startswith("new file") or "new file mode" in text:
            status = "added"
        elif "deleted file" in text:
            status = "deleted"
        elif "rename from" in text:
            status = "renamed"
        else:
            status = "modified"
        
        # Extract patch
        patch_match = re.search(r'@@.*@@(.*)', text, re.DOTALL)
        patch = patch_match.group(1).strip() if patch_match else ""
        
        # Count additions/deletions
        additions = len(re.findall(r'^\+[^+]', patch, re.MULTILINE))
        deletions = len(re.findall(r'^-[^-]', patch, re.MULTILINE))
        
        # Detect language
        language = self._detect_language(new_path)
        
        return FileDiff(
            filename=new_path,
            status=status,
            additions=additions,
            deletions=deletions,
            patch=patch,
            old_path=old_path if old_path != new_path else None,
            new_path=new_path,
            language=language
        )
    
    def _detect_language(self, filename: str) -> Optional[str]:
        """Detect programming language from filename."""
        for ext, lang in self.LANGUAGE_MAP.items():
            if filename.lower().endswith(ext):
                return lang
        return None


class DiffContextBuilder:
    """Build context information for diff analysis."""
    
    def build_context(self, pr_info: dict, files: List[FileDiff]) -> dict:
        """Build comprehensive context for diff analysis."""
        context = {
            "pr_id": pr_info.get("number"),
            "pr_title": pr_info.get("title", ""),
            "pr_description": pr_info.get("body", ""),
            "repository": pr_info.get("base", {}).get("repo", {}).get("full_name", ""),
            "branch": pr_info.get("head", {}).get("ref", ""),
            "base_branch": pr_info.get("base", {}).get("ref", ""),
            "author": pr_info.get("user", {}).get("login", ""),
            "files": [
                {
                    "filename": f.filename,
                    "status": f.status,
                    "additions": f.additions,
                    "deletions": f.deletions,
                    "language": f.language
                }
                for f in files
            ],
            "total_files": len(files),
            "total_additions": sum(f.additions for f in files),
            "total_deletions": sum(f.deletions for f in files)
        }
        
        # Add language breakdown
        language_counts = {}
        for f in files:
            lang = f.language or "other"
            language_counts[lang] = language_counts.get(lang, 0) + 1
        context["languages"] = language_counts
        
        return context