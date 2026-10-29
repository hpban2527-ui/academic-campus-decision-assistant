import re
from datasketch import MinHash, MinHashLSH
from config import SIMILARITY_THRESHOLD, NUM_PERM, SHINGLE_SIZE


def get_shingles(text: str, k: int = SHINGLE_SIZE) -> set[str]:
    """
    Generate a set of k-shingles (word n-grams) from text.
    Strips URLs and special characters, normalizes to lowercase.
    """
    if not text:
        return set()
    clean = re.sub(r"https?://\S+", "", text.lower())
    words = re.findall(r"\w+", clean)
    if not words:
        return set()
    if len(words) < k:
        return set(words)
    return {" ".join(words[i : i + k]) for i in range(len(words) - k + 1)}


def compute_minhash(text: str, num_perm: int = NUM_PERM) -> MinHash | None:
    """Generate a MinHash signature from text."""
    shingles = get_shingles(text)
    if not shingles:
        return None
    m = MinHash(num_perm=num_perm)
    for s in shingles:
        m.update(s.encode("utf-8"))
    return m


class PostDeduplicator:
    """Manage MinHash-LSH index to detect duplicate and cross-posted articles."""

    def __init__(self, threshold: float = SIMILARITY_THRESHOLD, num_perm: int = NUM_PERM):
        self.threshold = threshold
        self.num_perm = num_perm
        self.lsh = MinHashLSH(threshold=threshold, num_perm=num_perm)
        self.minhashes: dict[str, MinHash] = {}

    def index_post(self, post_id: str, text: str) -> bool:
        """Index a post if it contains valid text content."""
        if not post_id or not text:
            return False
        m = compute_minhash(text, self.num_perm)
        if not m:
            return False
        try:
            self.lsh.insert(post_id, m)
            self.minhashes[post_id] = m
            return True
        except ValueError:
            return False

    def find_duplicate(self, text: str) -> tuple[str, float] | None:
        """
        Search for similar posts in the LSH index.
        Returns (candidate_id, similarity) if Jaccard similarity >= threshold,
        otherwise returns None.
        """
        new_m = compute_minhash(text, self.num_perm)
        if not new_m:
            return None
        candidates = self.lsh.query(new_m)
        for cand_id in candidates:
            cand_m = self.minhashes.get(cand_id)
            if cand_m:
                sim = new_m.jaccard(cand_m)
                if sim >= self.threshold:
                    return cand_id, sim
        return None
