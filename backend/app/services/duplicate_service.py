"""
Duplicate Detection Service
- Exact duplicates: file hash + perceptual hash
- Near duplicates: fuzzy string matching (Damerau-Levenshtein)
- Semantic similarity: vector fingerprint comparison via FAISS
"""
import io
import hashlib
import logging
import pickle
from typing import Dict, Any, List, Optional, Tuple

import numpy as np
from PIL import Image
import imagehash
from rapidfuzz import fuzz, process
import jellyfish

logger = logging.getLogger(__name__)

# FAISS import (optional, graceful degradation)
try:
    import faiss
    FAISS_AVAILABLE = True
except ImportError:
    FAISS_AVAILABLE = False
    logger.warning("FAISS not available - vector similarity disabled")


class DuplicateDetector:
    """Multi-strategy duplicate detection for invoices."""

    def __init__(self):
        self.faiss_index = None
        self.index_map = {}  # faiss_idx -> invoice_id
        self.dimension = 256  # Fingerprint vector dimension
        self._init_faiss_index()

    def _init_faiss_index(self):
        """Initialize FAISS index for vector similarity search."""
        if FAISS_AVAILABLE:
            self.faiss_index = faiss.IndexFlatL2(self.dimension)
            logger.info("FAISS index initialized")

    # ──────────────────────────────
    # 1. Exact Duplicate Detection
    # ──────────────────────────────

    def compute_file_hash(self, file_bytes: bytes) -> str:
        """SHA-256 hash for exact file matching."""
        return hashlib.sha256(file_bytes).hexdigest()

    def compute_perceptual_hash(self, image: Image.Image) -> str:
        """
        Perceptual hash - robust to minor visual changes.
        Combines average hash + difference hash + wavelet hash.
        """
        ahash = str(imagehash.average_hash(image, hash_size=16))
        dhash = str(imagehash.dhash(image, hash_size=16))
        phash = str(imagehash.phash(image, hash_size=16))
        
        return f"{ahash}:{dhash}:{phash}"

    def check_exact_duplicate(
        self, file_hash: str, perceptual_hash: str, known_hashes: Dict[str, str]
    ) -> Dict[str, Any]:
        """
        Check for exact duplicates using file hash and perceptual hash.
        known_hashes: {invoice_id: file_hash}
        """
        result = {
            "is_exact_duplicate": False,
            "duplicate_of": None,
            "match_type": None,
            "score": 0,
        }

        # Check exact file hash
        for inv_id, known_hash in known_hashes.items():
            if file_hash == known_hash:
                result["is_exact_duplicate"] = True
                result["duplicate_of"] = inv_id
                result["match_type"] = "exact_file_hash"
                result["score"] = 100
                return result

        return result

    def compare_perceptual_hashes(
        self, hash1: str, hash2: str, threshold: int = 10
    ) -> Tuple[bool, float]:
        """Compare two perceptual hashes. Returns (is_similar, similarity_score)."""
        parts1 = hash1.split(":")
        parts2 = hash2.split(":")

        if len(parts1) != 3 or len(parts2) != 3:
            return False, 0.0

        total_distance = 0
        for h1, h2 in zip(parts1, parts2):
            ih1 = imagehash.hex_to_hash(h1)
            ih2 = imagehash.hex_to_hash(h2)
            total_distance += (ih1 - ih2)

        avg_distance = total_distance / 3
        # Convert distance to similarity (0-100)
        max_bits = 256  # 16x16 hash
        similarity = max(0, (1 - avg_distance / max_bits)) * 100

        return similarity > (100 - threshold), similarity

    # ──────────────────────────────
    # 2. Fuzzy String Matching
    # ──────────────────────────────

    def fuzzy_match_invoices(
        self, invoice_data: Dict[str, Any], known_invoices: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Fuzzy matching using multiple string similarity metrics:
        - Damerau-Levenshtein distance
        - Token sort ratio
        - Partial ratio
        """
        matches = []

        for known in known_invoices:
            score_components = []

            # Invoice number similarity
            if invoice_data.get("invoice_number") and known.get("invoice_number"):
                dl_distance = jellyfish.damerau_levenshtein_distance(
                    str(invoice_data["invoice_number"]),
                    str(known["invoice_number"])
                )
                max_len = max(
                    len(str(invoice_data["invoice_number"])),
                    len(str(known["invoice_number"]))
                )
                inv_sim = max(0, (1 - dl_distance / max_len)) * 100 if max_len > 0 else 0
                score_components.append(("invoice_number", inv_sim, 0.30))

            # Vendor name similarity
            if invoice_data.get("vendor_name") and known.get("vendor_name"):
                vendor_sim = fuzz.token_sort_ratio(
                    invoice_data["vendor_name"], known["vendor_name"]
                )
                score_components.append(("vendor_name", vendor_sim, 0.20))

            # Amount similarity
            if invoice_data.get("total_amount") and known.get("total_amount"):
                amt1 = float(invoice_data["total_amount"])
                amt2 = float(known["total_amount"])
                if amt1 > 0 and amt2 > 0:
                    amt_sim = (1 - abs(amt1 - amt2) / max(amt1, amt2)) * 100
                    score_components.append(("total_amount", amt_sim, 0.25))

            # Date proximity
            if invoice_data.get("invoice_date") and known.get("invoice_date"):
                try:
                    d1 = invoice_data["invoice_date"]
                    d2 = known["invoice_date"]
                    day_diff = abs((d1 - d2).days)
                    date_sim = max(0, (1 - day_diff / 365)) * 100
                    score_components.append(("invoice_date", date_sim, 0.15))
                except (TypeError, AttributeError):
                    pass

            # Raw text similarity
            if invoice_data.get("raw_text") and known.get("raw_text"):
                text_sim = fuzz.partial_ratio(
                    invoice_data["raw_text"][:500],
                    known["raw_text"][:500]
                )
                score_components.append(("raw_text", text_sim, 0.10))

            # Calculate weighted score
            if score_components:
                total_weight = sum(w for _, _, w in score_components)
                weighted_score = sum(s * w for _, s, w in score_components) / total_weight
                
                if weighted_score > 60:  # Only report significant matches
                    matches.append({
                        "invoice_id": known.get("id"),
                        "similarity_score": round(weighted_score, 2),
                        "components": {
                            name: round(score, 2)
                            for name, score, _ in score_components
                        },
                    })

        # Sort by similarity
        matches.sort(key=lambda x: x["similarity_score"], reverse=True)

        best_score = matches[0]["similarity_score"] if matches else 0

        return {
            "duplicate_score": round(best_score, 2),
            "is_near_duplicate": best_score > 80,
            "matches": matches[:10],  # Top 10 matches
            "total_matches": len(matches),
        }

    # ──────────────────────────────
    # 3. Vector Fingerprint (FAISS)
    # ──────────────────────────────

    def generate_fingerprint(self, image: Image.Image) -> np.ndarray:
        """
        Generate a vector fingerprint for an invoice image.
        Uses a combination of image features for robust matching.
        """
        # Resize to standard
        img = image.convert("L").resize((128, 128))
        arr = np.array(img, dtype=np.float32).flatten()
        
        # Normalize
        arr = arr / 255.0
        
        # DCT-like feature extraction (simplified)
        # Take features at different scales
        features = []
        
        # Global features
        features.extend([np.mean(arr), np.std(arr), np.median(arr)])
        
        # Block features (4x4 grid)
        block_size = 128 // 4
        for i in range(4):
            for j in range(4):
                block = arr[i * block_size * 128 + j * block_size:
                           i * block_size * 128 + (j + 1) * block_size]
                features.extend([np.mean(block), np.std(block)])
        
        # Histogram features
        hist, _ = np.histogram(arr, bins=64, range=(0, 1))
        hist = hist.astype(np.float32) / hist.sum()
        features.extend(hist.tolist())
        
        # Edge features (simple gradient)
        img_2d = arr.reshape(128, 128)
        dx = np.diff(img_2d, axis=1)
        dy = np.diff(img_2d, axis=0)
        features.extend([np.mean(np.abs(dx)), np.std(dx)])
        features.extend([np.mean(np.abs(dy)), np.std(dy)])
        
        # Pad/truncate to fixed dimension
        fingerprint = np.array(features[:self.dimension], dtype=np.float32)
        if len(fingerprint) < self.dimension:
            fingerprint = np.pad(fingerprint, (0, self.dimension - len(fingerprint)))
        
        # Normalize
        norm = np.linalg.norm(fingerprint)
        if norm > 0:
            fingerprint = fingerprint / norm
        
        return fingerprint

    def add_to_index(self, invoice_id: str, fingerprint: np.ndarray):
        """Add a fingerprint to the FAISS index."""
        if not FAISS_AVAILABLE or self.faiss_index is None:
            return

        idx = self.faiss_index.ntotal
        self.faiss_index.add(fingerprint.reshape(1, -1))
        self.index_map[idx] = invoice_id

    def search_similar(
        self, fingerprint: np.ndarray, k: int = 5, threshold: float = 0.5
    ) -> List[Dict[str, Any]]:
        """Search for similar fingerprints in the FAISS index."""
        if not FAISS_AVAILABLE or self.faiss_index is None or self.faiss_index.ntotal == 0:
            return []

        distances, indices = self.faiss_index.search(
            fingerprint.reshape(1, -1), min(k, self.faiss_index.ntotal)
        )

        results = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx >= 0 and dist < threshold:
                similarity = max(0, (1 - dist) * 100)
                results.append({
                    "invoice_id": self.index_map.get(int(idx), "unknown"),
                    "distance": round(float(dist), 6),
                    "similarity": round(similarity, 2),
                })

        return results

    # ──────────────────────────────
    # Full Detection Pipeline
    # ──────────────────────────────

    def detect_duplicates(
        self,
        file_bytes: bytes,
        image: Image.Image,
        invoice_data: Dict[str, Any],
        known_hashes: Dict[str, str],
        known_invoices: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Run full duplicate detection pipeline:
        1. Exact hash matching
        2. Perceptual hash comparison
        3. Fuzzy string matching
        4. Vector fingerprint similarity
        """
        # File hash
        file_hash = self.compute_file_hash(file_bytes)
        perceptual_hash = self.compute_perceptual_hash(image)
        fingerprint = self.generate_fingerprint(image)

        # Check exact duplicates
        exact_result = self.check_exact_duplicate(file_hash, perceptual_hash, known_hashes)

        # Fuzzy matching
        fuzzy_result = self.fuzzy_match_invoices(invoice_data, known_invoices)

        # Vector similarity
        vector_matches = self.search_similar(fingerprint)

        # Combined duplicate score
        scores = [
            exact_result["score"],
            fuzzy_result["duplicate_score"],
        ]
        if vector_matches:
            scores.append(max(m["similarity"] for m in vector_matches))

        duplicate_score = max(scores) if scores else 0

        return {
            "file_hash": file_hash,
            "perceptual_hash": perceptual_hash,
            "fingerprint": fingerprint,
            "duplicate_score": round(duplicate_score, 2),
            "is_duplicate": duplicate_score > 80,
            "exact_match": exact_result,
            "fuzzy_matches": fuzzy_result,
            "vector_matches": vector_matches,
            "summary": self._generate_summary(duplicate_score, exact_result, fuzzy_result),
        }

    def _generate_summary(
        self, score: float, exact: Dict, fuzzy: Dict
    ) -> str:
        """Generate human-readable duplicate analysis summary."""
        if exact["is_exact_duplicate"]:
            return f"🚨 EXACT DUPLICATE detected (matches invoice {exact['duplicate_of']})"
        elif score > 80:
            return f"⚠️ Near-duplicate detected (similarity: {score:.1f}%)"
        elif score > 60:
            return f"Potential duplicate flag (similarity: {score:.1f}%) - review recommended"
        else:
            return "No significant duplicates found"


# Singleton
duplicate_detector = DuplicateDetector()
