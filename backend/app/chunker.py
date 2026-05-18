"""
Diff Chunking Utilities
"""
from typing import List, Callable, Iterator


class DiffChunker:
    """Utility for chunking large diffs into manageable pieces."""
    
    def __init__(self, max_chunk_bytes: int = 30 * 1024):
        self.max_chunk_bytes = max_chunk_bytes
    
    def chunk_by_files(
        self,
        files: List[dict],
        content_extractor: Callable[[dict], str]
    ) -> Iterator[List[dict]]:
        """Chunk files by grouping them into batches."""
        current_batch = []
        current_size = 0
        
        for file in files:
            content = content_extractor(file)
            file_size = len(content.encode())
            
            # Single file exceeds limit - add anyway but truncate
            if file_size > self.max_chunk_bytes and not current_batch:
                yield [file]
                continue
            
            # Adding this file exceeds limit
            if current_size + file_size > self.max_chunk_bytes:
                yield current_batch
                current_batch = [file]
                current_size = file_size
            else:
                current_batch.append(file)
                current_size += file_size
        
        if current_batch:
            yield current_batch