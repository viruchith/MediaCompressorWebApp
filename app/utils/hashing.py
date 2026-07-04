import hashlib


def compute_file_hash(file_path: str, chunk_size: int = 8192) -> str:
    """Compute SHA-256 hex digest of a file, streaming in chunks."""
    sha = hashlib.sha256()
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            sha.update(chunk)
    return sha.hexdigest()
