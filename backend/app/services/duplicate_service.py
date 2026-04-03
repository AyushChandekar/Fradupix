"""
Duplicate Detection Service
- Exact duplicates: file hash + perceptual hash
- Near duplicates: fuzzy string matching (Damerau-Levenshtein)
- Semantic similarity: vector fingerprint comparison via FAISS
- FR-502: TF-IDF vectorization with cosine similarity for semantic line-item comparison
- FR-503: Same-vendor identical-amount time-window duplicate detection
"""
import io
import hashlib
import logging
import pickle
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple

import numpy as np
from PIL import Image
import imagehash
from rapidfuzz import fuzz, process
import jellyfish
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

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

    # ──────────────────────────────────────────────
    # 4. FR-502 – TF-IDF Semantic Line-Item Similarity
    # ──────────────────────────────────────────────

    def semantic_similarity(self, text1: str, text2: str) -> float:
        """
        Compute semantic similarity between two text strings using
        TF-IDF vectorization + cosine similarity.

        Returns a similarity score between 0.0 and 1.0.
        """
        if not text1 or not text2:
            return 0.0

        try:
            vectorizer = TfidfVectorizer()
            tfidf_matrix = vectorizer.fit_transform([text1, text2])
            sim_score = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:2])[0][0]
            return float(np.clip(sim_score, 0.0, 1.0))
        except ValueError:
            # Happens when both texts are empty or contain only stop-words
            return 0.0

    def check_semantic_duplicates(
        self,
        invoice_data: Dict[str, Any],
        known_invoices: List[Dict[str, Any]],
        threshold: float = 0.85,
    ) -> Dict[str, Any]:
        """
        FR-502: Compare line-item descriptions between an incoming invoice and
        known invoices using TF-IDF + cosine similarity.

        Flags matches whose similarity score exceeds *threshold* (default 0.85).

        Returns:
            {
                "semantic_score": <best match score 0-100>,
                "is_semantic_duplicate": bool,
                "matches": [ { invoice_id, similarity, matched_items }, ... ]
            }
        """
        incoming_items: List[str] = [
            str(item) for item in invoice_data.get("line_items", []) if item
        ]
        # Fall back to raw_text if no structured line items
        incoming_text = " ".join(incoming_items) if incoming_items else invoice_data.get("raw_text", "")

        if not incoming_text:
            return {"semantic_score": 0, "is_semantic_duplicate": False, "matches": []}

        matches = []
        for known in known_invoices:
            known_items: List[str] = [
                str(item) for item in known.get("line_items", []) if item
            ]
            known_text = " ".join(known_items) if known_items else known.get("raw_text", "")
            if not known_text:
                continue

            score = self.semantic_similarity(incoming_text, known_text)

            if score >= threshold:
                matched_pairs = []
                # Pairwise item-level comparison when structured line items exist
                if incoming_items and known_items:
                    for inc_item in incoming_items:
                        for kn_item in known_items:
                            pair_score = self.semantic_similarity(inc_item, kn_item)
                            if pair_score >= threshold:
                                matched_pairs.append({
                                    "incoming": inc_item,
                                    "known": kn_item,
                                    "similarity": round(pair_score, 4),
                                })

                matches.append({
                    "invoice_id": known.get("id"),
                    "similarity": round(score, 4),
                    "matched_items": matched_pairs,
                })

        matches.sort(key=lambda m: m["similarity"], reverse=True)
        best_score = matches[0]["similarity"] * 100 if matches else 0

        return {
            "semantic_score": round(best_score, 2),
            "is_semantic_duplicate": best_score >= threshold * 100,
            "matches": matches[:10],
        }

    # ──────────────────────────────────────────────────────────
    # 5. FR-503 – Same-Vendor / Same-Amount Time-Window Check
    # ──────────────────────────────────────────────────────────

    def check_time_window_duplicates(
        self,
        vendor_name: str,
        amount: float,
        invoice_date: Any,
        known_invoices: List[Dict[str, Any]],
        window_days: int = 90,
    ) -> Dict[str, Any]:
        """
        FR-503: Detect invoices with identical amounts from the same vendor
        within a configurable time window (default 90 days).

        Parameters:
            vendor_name   – vendor / supplier name on the incoming invoice
            amount        – total amount on the incoming invoice
            invoice_date  – date object (datetime.date or datetime.datetime)
            known_invoices – list of previously processed invoices
            window_days   – look-back / look-ahead window in days

        Returns:
            {
                "time_window_score": 0-100,
                "is_time_window_duplicate": bool,
                "matches": [ { invoice_id, vendor, amount, date, day_diff }, ... ]
            }
        """
        if not vendor_name or amount is None or invoice_date is None:
            return {"time_window_score": 0, "is_time_window_duplicate": False, "matches": []}

        # Normalise to datetime for arithmetic
        if isinstance(invoice_date, str):
            try:
                invoice_date = datetime.fromisoformat(invoice_date)
            except (ValueError, TypeError):
                return {"time_window_score": 0, "is_time_window_duplicate": False, "matches": []}

        matches = []
        for known in known_invoices:
            known_amount = known.get("total_amount")
            known_vendor = known.get("vendor_name", "")
            known_date = known.get("invoice_date")

            if known_amount is None or known_date is None or not known_vendor:
                continue

            if isinstance(known_date, str):
                try:
                    known_date = datetime.fromisoformat(known_date)
                except (ValueError, TypeError):
                    continue

            # Vendor fuzzy match (token_sort_ratio ≥ 85 counts as same vendor)
            vendor_sim = fuzz.token_sort_ratio(vendor_name, known_vendor)
            if vendor_sim < 85:
                continue

            # Exact amount match
            if float(known_amount) != float(amount):
                continue

            # Time-window check
            try:
                day_diff = abs((invoice_date - known_date).days)
            except (TypeError, AttributeError):
                continue

            if day_diff <= window_days:
                matches.append({
                    "invoice_id": known.get("id"),
                    "vendor": known_vendor,
                    "amount": float(known_amount),
                    "date": str(known_date),
                    "day_diff": day_diff,
                })

        matches.sort(key=lambda m: m["day_diff"])
        best_score = 100 if matches else 0

        return {
            "time_window_score": best_score,
            "is_time_window_duplicate": len(matches) > 0,
            "matches": matches[:10],
        }

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
        time_window_days: int = 90,
    ) -> Dict[str, Any]:
        """
        Run full duplicate detection pipeline:
        1. Exact hash matching          (40 % weight when matched → 100)
        2. Perceptual hash comparison
        3. Fuzzy string matching         (30 % weight)
        4. Vector fingerprint similarity
        5. FR-502: TF-IDF semantic similarity (20 % weight)
        6. FR-503: Time-window vendor/amount  (10 % weight)

        Combined duplicate_score is the weighted sum of the four signal
        categories:
            exact_hash  × 0.40
          + fuzzy       × 0.30
          + semantic    × 0.20
          + time_window × 0.10
        """
        # ---- existing checks ----
        file_hash = self.compute_file_hash(file_bytes)
        perceptual_hash = self.compute_perceptual_hash(image)
        fingerprint = self.generate_fingerprint(image)

        exact_result = self.check_exact_duplicate(file_hash, perceptual_hash, known_hashes)
        fuzzy_result = self.fuzzy_match_invoices(invoice_data, known_invoices)
        vector_matches = self.search_similar(fingerprint)

        # ---- FR-502: semantic line-item similarity ----
        semantic_result = self.check_semantic_duplicates(invoice_data, known_invoices)

        # ---- FR-503: time-window vendor/amount check ----
        time_window_result = self.check_time_window_duplicates(
            vendor_name=invoice_data.get("vendor_name", ""),
            amount=invoice_data.get("total_amount", 0),
            invoice_date=invoice_data.get("invoice_date"),
            known_invoices=known_invoices,
            window_days=time_window_days,
        )

        # ---- weighted composite score ----
        exact_score = exact_result["score"]                        # 0 or 100
        fuzzy_score = fuzzy_result["duplicate_score"]              # 0-100
        semantic_score = semantic_result["semantic_score"]          # 0-100
        time_window_score = time_window_result["time_window_score"]  # 0 or 100

        duplicate_score = (
            exact_score    * 0.40
            + fuzzy_score  * 0.30
            + semantic_score * 0.20
            + time_window_score * 0.10
        )

        return {
            "file_hash": file_hash,
            "perceptual_hash": perceptual_hash,
            "fingerprint": fingerprint,
            "duplicate_score": round(duplicate_score, 2),
            "is_duplicate": duplicate_score > 80,
            "exact_match": exact_result,
            "fuzzy_matches": fuzzy_result,
            "vector_matches": vector_matches,
            "semantic_matches": semantic_result,
            "time_window_matches": time_window_result,
            "summary": self._generate_summary(
                duplicate_score, exact_result, fuzzy_result,
                semantic_result, time_window_result,
            ),
        }

    def _generate_summary(
        self,
        score: float,
        exact: Dict,
        fuzzy: Dict,
        semantic: Optional[Dict] = None,
        time_window: Optional[Dict] = None,
    ) -> str:
        """Generate human-readable duplicate analysis summary."""
        if exact["is_exact_duplicate"]:
            return f"EXACT DUPLICATE detected (matches invoice {exact['duplicate_of']})"

        flags: List[str] = []
        if semantic and semantic.get("is_semantic_duplicate"):
            flags.append(
                f"semantic line-item match ({semantic['semantic_score']:.1f}%)"
            )
        if time_window and time_window.get("is_time_window_duplicate"):
            tw_match = time_window["matches"][0]
            flags.append(
                f"same vendor+amount within {tw_match['day_diff']} days "
                f"(invoice {tw_match['invoice_id']})"
            )

        if score > 80:
            detail = f"Near-duplicate detected (similarity: {score:.1f}%)"
            if flags:
                detail += " | " + "; ".join(flags)
            return detail
        elif score > 60:
            detail = f"Potential duplicate flag (similarity: {score:.1f}%) - review recommended"
            if flags:
                detail += " | " + "; ".join(flags)
            return detail
        elif flags:
            return "Flagged: " + "; ".join(flags)
        else:
            return "No significant duplicates found"


# Singleton
duplicate_detector = DuplicateDetector()
