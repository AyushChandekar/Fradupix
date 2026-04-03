"""
Fraud Detection Service - Detect forgeries and manipulations in invoices
Combines image forensics (ELA, metadata analysis, font consistency,
vendor template matching, and heatmap generation) with content validation.

Implements:
  FR-400  Forgery detection pipeline
  FR-402  Font consistency analysis
  FR-403  Vendor template matching (SSIM)
  FR-405  Pixel-level heatmap overlay
"""
import io
import logging
import hashlib
from typing import Dict, Any, List, Optional, Tuple
from PIL import Image, ImageChops
import numpy as np
import cv2

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

    # ------------------------------------------------------------------
    # FR-402: Font consistency analysis
    # ------------------------------------------------------------------
    def analyze_font_consistency(self, image: Image.Image) -> Dict[str, Any]:
        """
        Analyse text regions for font-size / weight consistency (FR-402).

        Approach
        --------
        1. Convert image to grayscale, apply adaptive thresholding to isolate
           text-like regions.
        2. Find connected-component contours that look like characters (aspect-
           ratio and area filters).
        3. Cluster detected character heights using a simple 1-D histogram to
           identify dominant font sizes.
        4. Flag regions whose character heights fall outside the dominant
           clusters (outliers beyond 1.5x IQR).
        5. Return a 0-100 *inconsistency* score and a list of flagged regions.
        """
        try:
            # Convert PIL -> OpenCV (BGR)
            cv_img = cv2.cvtColor(np.array(image.convert("RGB")), cv2.COLOR_RGB2BGR)
            gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)

            # Adaptive threshold to binarise text
            binary = cv2.adaptiveThreshold(
                gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY_INV, 15, 10,
            )

            # Morphological close to merge nearby strokes into character blobs
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
            binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=1)

            # Find contours (character-level candidates)
            contours, _ = cv2.findContours(
                binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE,
            )

            # Filter contours that look like individual characters
            char_heights: List[float] = []
            char_regions: List[Dict[str, Any]] = []

            img_h, img_w = gray.shape
            min_char_area = max(9, img_h * img_w * 0.00002)  # adaptive lower bound
            max_char_area = img_h * img_w * 0.02               # skip huge blobs

            for cnt in contours:
                x, y, w, h = cv2.boundingRect(cnt)
                area = w * h
                if area < min_char_area or area > max_char_area:
                    continue
                aspect = w / max(h, 1)
                # Characters are taller-than-wide or roughly square
                if aspect > 3.0 or h < 4:
                    continue
                char_heights.append(float(h))
                char_regions.append({"x": int(x), "y": int(y), "w": int(w), "h": int(h)})

            if len(char_heights) < 5:
                # Too few characters detected to make a judgment
                return {
                    "font_consistency_score": 0,
                    "inconsistent_regions": [],
                    "total_characters_detected": len(char_heights),
                    "detail": "Insufficient text regions for analysis",
                }

            heights = np.array(char_heights)
            q1, q3 = float(np.percentile(heights, 25)), float(np.percentile(heights, 75))
            iqr = q3 - q1
            lower_bound = q1 - 1.5 * max(iqr, 1)
            upper_bound = q3 + 1.5 * max(iqr, 1)

            inconsistent_regions: List[Dict[str, Any]] = []
            for region, h in zip(char_regions, char_heights):
                if h < lower_bound or h > upper_bound:
                    region["char_height"] = h
                    region["expected_range"] = [round(lower_bound, 1), round(upper_bound, 1)]
                    inconsistent_regions.append(region)

            # Score: ratio of outlier characters vs total, scaled to 0-100
            outlier_ratio = len(inconsistent_regions) / len(char_heights)
            score = min(100, round(outlier_ratio * 300, 2))  # amplify signal

            return {
                "font_consistency_score": score,
                "inconsistent_regions": inconsistent_regions[:30],
                "total_characters_detected": len(char_heights),
                "dominant_height_range": [round(lower_bound, 1), round(upper_bound, 1)],
                "is_suspicious": score > 35,
            }
        except Exception as e:
            logger.error(f"Font consistency analysis failed: {e}")
            return {"font_consistency_score": 0, "inconsistent_regions": [], "error": str(e)}

    # ------------------------------------------------------------------
    # FR-403: Vendor template matching (SSIM)
    # ------------------------------------------------------------------
    @staticmethod
    def _compute_ssim(img_a: np.ndarray, img_b: np.ndarray) -> float:
        """
        Compute the Structural Similarity Index (SSIM) between two
        single-channel images of the same size.  Pure-numpy fallback so
        scikit-image is *not* required.

        Reference: Wang et al., "Image Quality Assessment: From Error
        Visibility to Structural Similarity", IEEE TIP 2004.
        """
        C1 = (0.01 * 255) ** 2
        C2 = (0.03 * 255) ** 2

        a = img_a.astype(np.float64)
        b = img_b.astype(np.float64)

        mu_a = cv2.GaussianBlur(a, (11, 11), 1.5)
        mu_b = cv2.GaussianBlur(b, (11, 11), 1.5)

        mu_a_sq = mu_a ** 2
        mu_b_sq = mu_b ** 2
        mu_ab = mu_a * mu_b

        sigma_a_sq = cv2.GaussianBlur(a ** 2, (11, 11), 1.5) - mu_a_sq
        sigma_b_sq = cv2.GaussianBlur(b ** 2, (11, 11), 1.5) - mu_b_sq
        sigma_ab = cv2.GaussianBlur(a * b, (11, 11), 1.5) - mu_ab

        numerator = (2 * mu_ab + C1) * (2 * sigma_ab + C2)
        denominator = (mu_a_sq + mu_b_sq + C1) * (sigma_a_sq + sigma_b_sq + C2)

        ssim_map = numerator / denominator
        return float(np.mean(ssim_map))

    def compare_vendor_template(
        self, image: Image.Image, template_image: Image.Image,
    ) -> Dict[str, Any]:
        """
        Compare the header / logo area of *image* against a registered
        vendor *template_image* using SSIM scoring (FR-403).

        The method extracts the top 25% of the invoice (typical header /
        logo area) and resizes both crops to a common dimension before
        computing SSIM.

        Returns
        -------
        dict with ``logo_match_score`` (0-100, higher = better match),
        raw ``ssim_value``, and a boolean ``is_match``.
        """
        try:
            # Extract header region (top 25 %) from the invoice image
            w, h = image.size
            header_crop = image.crop((0, 0, w, int(h * 0.25)))

            # Resize both to a common size for fair comparison
            common_size = (400, 150)
            header_resized = header_crop.convert("L").resize(common_size, Image.Resampling.LANCZOS)
            template_resized = template_image.convert("L").resize(common_size, Image.Resampling.LANCZOS)

            arr_header = np.array(header_resized)
            arr_template = np.array(template_resized)

            ssim_val = self._compute_ssim(arr_header, arr_template)
            # Map SSIM (range roughly -1..1, typically 0..1) to 0-100
            logo_match_score = max(0.0, min(100.0, ssim_val * 100))

            return {
                "logo_match_score": round(logo_match_score, 2),
                "ssim_value": round(ssim_val, 6),
                "is_match": logo_match_score >= 70,
            }
        except Exception as e:
            logger.error(f"Vendor template comparison failed: {e}")
            return {"logo_match_score": 0, "ssim_value": 0.0, "error": str(e)}

    # ------------------------------------------------------------------
    # FR-405: Pixel-level heatmap overlay
    # ------------------------------------------------------------------
    def generate_heatmap(
        self,
        image: Image.Image,
        ela_result: Optional[Dict[str, Any]] = None,
        font_result: Optional[Dict[str, Any]] = None,
        copy_paste_result: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Generate a pixel-level heatmap overlay combining evidence from
        ELA, font-consistency, and copy-paste analyses (FR-405).

        The heatmap is rendered as a semi-transparent colour overlay on
        top of the original image and returned as PNG bytes.

        Parameters
        ----------
        image : PIL.Image
            Original invoice image.
        ela_result, font_result, copy_paste_result : dict, optional
            Pre-computed analysis results.  When *None* the corresponding
            analysis is run on-the-fly.

        Returns
        -------
        dict with ``heatmap_png_bytes`` (bytes), ``width``, ``height``.
        """
        try:
            rgb = image.convert("RGB")
            cv_img = cv2.cvtColor(np.array(rgb), cv2.COLOR_RGB2BGR)
            h, w = cv_img.shape[:2]

            # Accumulator for the heat signal (float32, 0..1)
            heat = np.zeros((h, w), dtype=np.float32)

            # --- ELA contribution -------------------------------------------
            if ela_result is None:
                ela_result = self.error_level_analysis(image)
            for region in ela_result.get("suspicious_regions", []):
                rx, ry = region["x"], region["y"]
                rw, rh = region["width"], region["height"]
                intensity = min(1.0, region.get("suspicion_ratio", 0.1) * 3)
                heat[ry:ry + rh, rx:rx + rw] = np.maximum(
                    heat[ry:ry + rh, rx:rx + rw], intensity,
                )

            # --- Font-consistency contribution ------------------------------
            if font_result is None:
                font_result = self.analyze_font_consistency(image)
            for region in font_result.get("inconsistent_regions", []):
                rx, ry = region["x"], region["y"]
                rw, rh = region["w"], region["h"]
                # Pad slightly so small characters are visible on the map
                pad = 4
                y1 = max(0, ry - pad)
                y2 = min(h, ry + rh + pad)
                x1 = max(0, rx - pad)
                x2 = min(w, rx + rw + pad)
                heat[y1:y2, x1:x2] = np.maximum(heat[y1:y2, x1:x2], 0.7)

            # --- Copy-paste contribution ------------------------------------
            if copy_paste_result is None:
                copy_paste_result = self.check_copy_paste(image)
            block_size = 16
            for dup in copy_paste_result.get("duplicate_regions", []):
                for key in ("region1", "region2"):
                    rx = dup[key]["x"]
                    ry = dup[key]["y"]
                    heat[ry:ry + block_size, rx:rx + block_size] = np.maximum(
                        heat[ry:ry + block_size, rx:rx + block_size], 0.85,
                    )

            # Smooth the heat map for visual clarity
            heat = cv2.GaussianBlur(heat, (31, 31), 0)
            heat = np.clip(heat, 0, 1)

            # Convert heat to a colour map and blend with the original
            heat_u8 = (heat * 255).astype(np.uint8)
            heatmap_colour = cv2.applyColorMap(heat_u8, cv2.COLORMAP_JET)
            # Only overlay where heat > 0 to keep untouched areas clean
            alpha = 0.5
            mask = heat_u8 > 10
            overlay = cv_img.copy()
            overlay[mask] = cv2.addWeighted(
                cv_img[mask], 1 - alpha, heatmap_colour[mask], alpha, 0,
            )

            # Encode as PNG bytes
            success, png_buffer = cv2.imencode(".png", overlay)
            if not success:
                raise RuntimeError("Failed to encode heatmap image as PNG")

            png_bytes = png_buffer.tobytes()

            return {
                "heatmap_png_bytes": png_bytes,
                "width": w,
                "height": h,
                "size_bytes": len(png_bytes),
            }
        except Exception as e:
            logger.error(f"Heatmap generation failed: {e}")
            return {"heatmap_png_bytes": b"", "error": str(e)}

    # ------------------------------------------------------------------
    # Full detection pipeline
    # ------------------------------------------------------------------
    def detect_forgery(self, image: Image.Image) -> Dict[str, Any]:
        """
        Run full forgery detection pipeline:
        1. Error Level Analysis  (ELA)
        2. Metadata Analysis
        3. Copy-Paste Detection
        4. Font Consistency Analysis  (FR-402)
        5. Heatmap Generation          (FR-405)

        Weighted scoring:
            ELA 30% | Metadata 25% | Copy-Paste 15% | Font Consistency 30%
        """
        ela_result = self.error_level_analysis(image)
        metadata_result = self.analyze_metadata(image)
        copy_paste_result = self.check_copy_paste(image)
        font_result = self.analyze_font_consistency(image)

        # Generate the pixel-level heatmap overlay (FR-405)
        heatmap_result = self.generate_heatmap(
            image,
            ela_result=ela_result,
            font_result=font_result,
            copy_paste_result=copy_paste_result,
        )

        # Combined forgery score (weighted average)
        forgery_score = (
            ela_result.get("ela_score", 0) * 0.30 +
            metadata_result.get("metadata_score", 0) * 0.25 +
            copy_paste_result.get("copy_paste_score", 0) * 0.15 +
            font_result.get("font_consistency_score", 0) * 0.30
        )

        evidence = {
            "ela": ela_result,
            "metadata": metadata_result,
            "copy_paste": copy_paste_result,
            "font_consistency": font_result,
        }

        return {
            "forgery_score": round(forgery_score, 2),
            "is_forged": forgery_score > 50,
            "evidence": evidence,
            "heatmap": heatmap_result,
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
            parts.append("Moderate signs of image manipulation detected.")
        else:
            parts.append("HIGH probability of digital forgery detected!")

        ela = evidence.get("ela", {})
        if ela.get("is_suspicious"):
            regions = len(ela.get("suspicious_regions", []))
            parts.append(f"ELA found {regions} suspicious region(s).")

        meta = evidence.get("metadata", {})
        for finding in meta.get("findings", []):
            parts.append(f"- {finding}")

        cp = evidence.get("copy_paste", {})
        if cp.get("is_suspicious"):
            parts.append(
                f"Copy-paste detection: {cp.get('total_duplicates', 0)} duplicate regions found."
            )

        font = evidence.get("font_consistency", {})
        if font.get("is_suspicious"):
            n_inconsistent = len(font.get("inconsistent_regions", []))
            parts.append(
                f"Font consistency: {n_inconsistent} region(s) with unexpected font size changes."
            )

        return " ".join(parts)


# Singleton
forgery_detector = ForgeryDetector()
