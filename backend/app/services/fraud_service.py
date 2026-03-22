"""
Fraud Detection Service - Detect forgeries and manipulations in invoices
Combines image forensics (ELA, metadata analysis) with content validation
"""
import io
import logging
import hashlib
from typing import Dict, Any, List, Optional, Tuple
from PIL import Image, ImageChops
import numpy as np

logger = logging.getLogger(__name__)


class ForgeryDetector:
    """Detect digital forgeries in invoice images using forensic techniques."""

    def __init__(self):
        self.ela_quality = 90  # JPEG quality for ELA
        self.ela_threshold = 25  # Pixel difference threshold
        self.suspicious_region_threshold = 0.05  # 5% of image area

    def error_level_analysis(self, image: Image.Image) -> Dict[str, Any]:
        """
        Error Level Analysis (ELA) - detects edited regions in images.
        Resaves image at known quality and compares differences.
        Edited regions show higher error levels.
        """
        try:
            # Convert to RGB if needed
            if image.mode != "RGB":
                image = image.convert("RGB")

            # Save at specific quality
            buffer = io.BytesIO()
            image.save(buffer, "JPEG", quality=self.ela_quality)
            buffer.seek(0)
            resaved = Image.open(buffer)

            # Calculate pixel-level differences
            ela_image = ImageChops.difference(image, resaved)
            ela_array = np.array(ela_image)

            # Analyze error levels
            mean_error = float(np.mean(ela_array))
            max_error = float(np.max(ela_array))
            std_error = float(np.std(ela_array))

            # Find suspicious regions (high error areas)
            threshold = mean_error + 2 * std_error
            suspicious_mask = np.any(ela_array > threshold, axis=2)
            suspicious_ratio = float(np.sum(suspicious_mask)) / suspicious_mask.size

            # Detect clustered edits (suspicious if concentrated)
            suspicious_regions = self._find_suspicious_clusters(suspicious_mask)

            # Score: 0-100 (higher = more likely forged)
            ela_score = min(100, (suspicious_ratio * 500) + (max_error / 255 * 30))

            return {
                "ela_score": round(ela_score, 2),
                "mean_error": round(mean_error, 4),
                "max_error": round(max_error, 4),
                "std_error": round(std_error, 4),
                "suspicious_ratio": round(suspicious_ratio, 6),
                "suspicious_regions": suspicious_regions,
                "is_suspicious": ela_score > 40,
            }
        except Exception as e:
            logger.error(f"ELA analysis failed: {e}")
            return {"ela_score": 0, "error": str(e)}

    def _find_suspicious_clusters(self, mask: np.ndarray) -> List[Dict[str, int]]:
        """Find clusters of suspicious pixels."""
        regions = []
        h, w = mask.shape

        # Simple grid-based clustering
        grid_size = 64
        for y in range(0, h, grid_size):
            for x in range(0, w, grid_size):
                block = mask[y:y + grid_size, x:x + grid_size]
                ratio = np.sum(block) / block.size
                if ratio > self.suspicious_region_threshold:
                    regions.append({
                        "x": int(x),
                        "y": int(y),
                        "width": min(grid_size, w - x),
                        "height": min(grid_size, h - y),
                        "suspicion_ratio": round(float(ratio), 4),
                    })

        return regions[:20]  # Limit to top 20 regions

    def analyze_metadata(self, image: Image.Image) -> Dict[str, Any]:
        """Analyze image metadata for signs of manipulation."""
        findings = []
        score = 0

        # Check EXIF data
        exif_data = {}
        try:
            exif = image._getexif()
            if exif:
                exif_data = {str(k): str(v) for k, v in exif.items()}
                
                # Check for editing software
                software_tags = ["271", "305", "11"]  # Make, Software, ProcessingSoftware
                for tag in software_tags:
                    if tag in exif_data:
                        sw = exif_data[tag].lower()
                        if any(editor in sw for editor in ["photoshop", "gimp", "paint", "editor"]):
                            findings.append(f"Edited with: {exif_data[tag]}")
                            score += 30
            else:
                findings.append("No EXIF data (could indicate stripping)")
                score += 10
        except Exception:
            findings.append("EXIF extraction failed")

        # Check image properties
        if image.mode == "RGBA":
            findings.append("Image has alpha channel (unusual for scanned invoices)")
            score += 15

        # Check DPI
        dpi = image.info.get("dpi", (0, 0))
        if dpi and (dpi[0] < 72 or dpi[1] < 72):
            findings.append(f"Low DPI ({dpi[0]}x{dpi[1]}) - possibly screenshot")
            score += 10

        # Check for suspicious image dimensions
        w, h = image.size
        if w < 200 or h < 200:
            findings.append("Very small image - suspicious quality")
            score += 15

        return {
            "metadata_score": min(100, score),
            "findings": findings,
            "has_exif": bool(exif_data),
            "image_mode": image.mode,
            "dimensions": {"width": w, "height": h},
            "dpi": dpi if dpi else None,
        }

    def check_copy_paste(self, image: Image.Image) -> Dict[str, Any]:
        """Detect copy-paste forgery using block matching."""
        try:
            if image.mode != "L":
                gray = image.convert("L")
            else:
                gray = image

            # Resize for performance
            max_size = 512
            ratio = min(max_size / gray.width, max_size / gray.height)
            if ratio < 1:
                gray = gray.resize(
                    (int(gray.width * ratio), int(gray.height * ratio)),
                    Image.Resampling.LANCZOS
                )

            arr = np.array(gray, dtype=np.float32)
            block_size = 16
            h, w = arr.shape
            
            blocks = {}
            duplicates = []

            for y in range(0, h - block_size, block_size // 2):
                for x in range(0, w - block_size, block_size // 2):
                    block = arr[y:y + block_size, x:x + block_size]
                    block_hash = hashlib.md5(block.tobytes()).hexdigest()
                    
                    if block_hash in blocks:
                        prev_x, prev_y = blocks[block_hash]
                        dist = ((x - prev_x) ** 2 + (y - prev_y) ** 2) ** 0.5
                        if dist > block_size * 2:  # Not adjacent
                            duplicates.append({
                                "region1": {"x": int(prev_x), "y": int(prev_y)},
                                "region2": {"x": int(x), "y": int(y)},
                                "distance": round(dist, 2),
                            })
                    else:
                        blocks[block_hash] = (x, y)

            score = min(100, len(duplicates) * 5)

            return {
                "copy_paste_score": score,
                "duplicate_regions": duplicates[:10],
                "total_duplicates": len(duplicates),
                "is_suspicious": score > 20,
            }
        except Exception as e:
            logger.error(f"Copy-paste detection failed: {e}")
            return {"copy_paste_score": 0, "error": str(e)}

    def detect_forgery(self, image: Image.Image) -> Dict[str, Any]:
        """
        Run full forgery detection pipeline:
        1. Error Level Analysis (ELA)
        2. Metadata Analysis
        3. Copy-Paste Detection
        """
        ela_result = self.error_level_analysis(image)
        metadata_result = self.analyze_metadata(image)
        copy_paste_result = self.check_copy_paste(image)

        # Combined forgery score (weighted average)
        forgery_score = (
            ela_result.get("ela_score", 0) * 0.45 +
            metadata_result.get("metadata_score", 0) * 0.25 +
            copy_paste_result.get("copy_paste_score", 0) * 0.30
        )

        evidence = {
            "ela": ela_result,
            "metadata": metadata_result,
            "copy_paste": copy_paste_result,
        }

        return {
            "forgery_score": round(forgery_score, 2),
            "is_forged": forgery_score > 50,
            "evidence": evidence,
            "summary": self._generate_summary(forgery_score, evidence),
        }

    def _generate_summary(self, score: float, evidence: Dict) -> str:
        """Generate human-readable forgery analysis summary."""
        parts = []
        
        if score < 20:
            parts.append("No significant signs of manipulation detected.")
        elif score < 50:
            parts.append("Minor inconsistencies detected - manual review advised.")
        elif score < 75:
            parts.append("⚠️ Moderate signs of image manipulation detected.")
        else:
            parts.append("🚨 HIGH probability of digital forgery detected!")

        ela = evidence.get("ela", {})
        if ela.get("is_suspicious"):
            regions = len(ela.get("suspicious_regions", []))
            parts.append(f"ELA found {regions} suspicious region(s).")

        meta = evidence.get("metadata", {})
        for finding in meta.get("findings", []):
            parts.append(f"• {finding}")

        cp = evidence.get("copy_paste", {})
        if cp.get("is_suspicious"):
            parts.append(f"Copy-paste detection: {cp.get('total_duplicates', 0)} duplicate regions found.")

        return " ".join(parts)


# Singleton
forgery_detector = ForgeryDetector()
