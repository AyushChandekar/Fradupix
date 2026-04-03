"""
OCR Service - Extract structured data from invoice images/PDFs

FR-200: Optical Character Recognition Pipeline
  FR-201: OpenCV preprocessing (deskew, denoise, binarize, 300 DPI normalization)
  FR-202: Tesseract 5 + EasyOCR ensemble with confidence-weighted merging
  FR-203: Structured field extraction (invoice number, dates, vendor, line items,
          amounts, currency, payment terms)
  FR-205: Multi-language OCR (English, German, French, Spanish, Hindi)
  FR-206: Structured JSON output with raw OCR text
"""
import re
import io
import math
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple

import numpy as np
import cv2
from PIL import Image, ImageEnhance, ImageFilter
import pytesseract

# EasyOCR is optional -- graceful fallback to Tesseract-only mode
try:
    import easyocr

    _EASYOCR_AVAILABLE = True
except ImportError:
    _EASYOCR_AVAILABLE = False

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tesseract language code mapping
# ---------------------------------------------------------------------------
_TESSERACT_LANG_MAP: Dict[str, str] = {
    "en": "eng",
    "de": "deu",
    "fr": "fra",
    "es": "spa",
    "hi": "hin",
}

# EasyOCR uses two-letter codes directly
_EASYOCR_LANG_MAP: Dict[str, str] = {
    "en": "en",
    "de": "de",
    "fr": "fr",
    "es": "es",
    "hi": "hi",
}

# Default target DPI for resolution normalization (FR-201)
_TARGET_DPI = 300


class OCRService:
    """Extract structured data from invoice documents.

    Implements the FR-200 family of requirements:
    * OpenCV-based image preprocessing (FR-201)
    * Dual-engine OCR with confidence-weighted merging (FR-202)
    * Structured field + line-item extraction (FR-203)
    * Multi-language support (FR-205)
    * Structured JSON output with raw text (FR-206)
    """

    # ------------------------------------------------------------------
    # Regex patterns for structured field extraction  (FR-203)
    # ------------------------------------------------------------------
    PATTERNS: Dict[str, List[str]] = {
        "invoice_number": [
            r"(?:invoice\s*(?:#|no\.?|number)\s*[:.]?\s*)([A-Z0-9\-\/]+)",
            r"(?:inv\s*(?:#|no\.?)\s*[:.]?\s*)([A-Z0-9\-\/]+)",
            r"(?:Rechnungsnummer|Facture\s*N[o°]\.?|N[uú]mero\s*de\s*factura)\s*[:.]?\s*([A-Z0-9\-\/]+)",
            r"(?:#\s*)(\d{4,})",
        ],
        "date": [
            r"(?:invoice\s*date|date\s*of\s*invoice|date|Rechnungsdatum|Date\s*de\s*facture|Fecha)\s*[:.]?\s*(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})",
            r"(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{2,4})",
            r"(\d{4}-\d{2}-\d{2})",
        ],
        "due_date": [
            r"(?:due\s*date|payment\s*due|pay\s*by|F[aä]lligkeitsdatum|Date\s*d'[eé]ch[eé]ance|Fecha\s*de\s*vencimiento)\s*[:.]?\s*(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})",
            r"(?:due\s*date|payment\s*due)\s*[:.]?\s*(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{2,4})",
        ],
        "total_amount": [
            r"(?:total\s*(?:amount|due|payable)?)\s*[:.]?\s*[\$\u20ac\u00a3\u20b9]?\s*([\d,]+\.?\d{0,2})",
            r"(?:grand\s*total|amount\s*due|balance\s*due|Gesamtbetrag|Montant\s*total|Total\s*general)\s*[:.]?\s*[\$\u20ac\u00a3\u20b9]?\s*([\d,]+\.?\d{0,2})",
            r"(?:total)\s*[\$\u20ac\u00a3\u20b9]?\s*([\d,]+\.\d{2})",
        ],
        "subtotal": [
            r"(?:sub\s*total|subtotal|Zwischensumme|Sous[\-\s]?total|Subtotal)\s*[:.]?\s*[\$\u20ac\u00a3\u20b9]?\s*([\d,]+\.?\d{0,2})",
        ],
        "tax": [
            r"(?:tax|vat|gst|sales\s*tax|MwSt|TVA|IVA|USt)\s*[:.]?\s*[\$\u20ac\u00a3\u20b9]?\s*([\d,]+\.?\d{0,2})",
            r"(?:tax)\s*\(?\d*\.?\d*%?\)?\s*[:.]?\s*[\$\u20ac\u00a3\u20b9]?\s*([\d,]+\.?\d{0,2})",
        ],
        "vendor_name": [
            r"(?:from|vendor|supplier|bill\s*from|sold\s*by|Lieferant|Fournisseur|Proveedor)\s*[:.]?\s*([A-Z][A-Za-z\s&\.,]+?)(?:\n|$)",
        ],
        "buyer_name": [
            r"(?:to|bill\s*to|sold\s*to|customer|client|Kunde|Client|Cliente)\s*[:.]?\s*([A-Z][A-Za-z\s&\.,]+?)(?:\n|$)",
        ],
        "currency": [
            r"(?:currency|curr\.?|w[aä]hrung|devise|moneda)\s*[:.]?\s*([A-Z]{3})",
            r"(\$|USD)",
            r"(\u20ac|EUR)",
            r"(\u00a3|GBP)",
            r"(\u20b9|INR)",
            r"(CHF)",
        ],
        "payment_terms": [
            r"(?:payment\s*terms?|terms?\s*of\s*payment|Zahlungsbedingungen|Conditions?\s*de\s*paiement|Condiciones\s*de\s*pago)\s*[:.]?\s*(.+?)(?:\n|$)",
            r"(?:net\s*\d+|due\s*(?:on|upon)\s*receipt|payable\s*within\s*\d+\s*days?)",
            r"(Net\s*\d+)",
            r"(Due\s*(?:on|upon)\s*receipt)",
        ],
    }

    DATE_FORMATS = [
        "%m/%d/%Y", "%d/%m/%Y", "%m-%d-%Y", "%d-%m-%Y",
        "%m.%d.%Y", "%d.%m.%Y", "%Y-%m-%d",
        "%d %B %Y", "%d %b %Y", "%B %d, %Y", "%b %d, %Y",
        "%m/%d/%y", "%d/%m/%y",
    ]

    # Currency symbol -> ISO code mapping
    _CURRENCY_SYMBOL_MAP: Dict[str, str] = {
        "$": "USD",
        "USD": "USD",
        "\u20ac": "EUR",
        "EUR": "EUR",
        "\u00a3": "GBP",
        "GBP": "GBP",
        "\u20b9": "INR",
        "INR": "INR",
        "CHF": "CHF",
    }

    def __init__(self) -> None:
        # Lazily initialised EasyOCR readers keyed by language tuple
        self._easyocr_readers: Dict[Tuple[str, ...], Any] = {}

    # ------------------------------------------------------------------
    # FR-201  Image preprocessing with OpenCV
    # ------------------------------------------------------------------

    @staticmethod
    def _pil_to_cv2(image: Image.Image) -> np.ndarray:
        """Convert a PIL Image to an OpenCV BGR/grayscale numpy array."""
        if image.mode == "L":
            return np.array(image)
        rgb = image.convert("RGB")
        return cv2.cvtColor(np.array(rgb), cv2.COLOR_RGB2BGR)

    @staticmethod
    def _cv2_to_pil(img: np.ndarray) -> Image.Image:
        """Convert an OpenCV array back to a PIL Image."""
        if len(img.shape) == 2:
            return Image.fromarray(img)
        return Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))

    @staticmethod
    def _normalize_resolution(image: Image.Image, target_dpi: int = _TARGET_DPI) -> Image.Image:
        """Scale the image so its effective resolution is *target_dpi*.

        If the image carries DPI metadata we use it; otherwise we assume 72 DPI
        (common screen default) and scale up accordingly.
        """
        info = image.info
        dpi = info.get("dpi", (72, 72))
        # PIL may return dpi as float tuple
        try:
            current_dpi = float(dpi[0])
        except (TypeError, IndexError):
            current_dpi = 72.0

        if current_dpi <= 0:
            current_dpi = 72.0

        if abs(current_dpi - target_dpi) < 5:
            # Already close enough
            return image

        scale = target_dpi / current_dpi
        new_w = int(image.width * scale)
        new_h = int(image.height * scale)
        resized = image.resize((new_w, new_h), Image.LANCZOS)
        resized.info["dpi"] = (target_dpi, target_dpi)
        return resized

    @staticmethod
    def _deskew(gray: np.ndarray) -> np.ndarray:
        """Deskew a grayscale image using minAreaRect on contours."""
        # Threshold to find text regions
        thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]

        # Find all contour points
        contours, _ = cv2.findContours(thresh, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return gray

        # Gather all contour points and compute the minimum area rectangle
        all_points = np.concatenate(contours)
        rect = cv2.minAreaRect(all_points)
        angle = rect[-1]

        # minAreaRect returns angles in [-90, 0); normalise to a small skew
        if angle < -45:
            angle = 90 + angle
        elif angle > 45:
            angle = angle - 90

        # Only correct if skew is meaningful (> 0.5 deg)
        if abs(angle) < 0.5:
            return gray

        (h, w) = gray.shape[:2]
        center = (w // 2, h // 2)
        rotation_matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
        rotated = cv2.warpAffine(
            gray, rotation_matrix, (w, h),
            flags=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_REPLICATE,
        )
        return rotated

    @staticmethod
    def _denoise(gray: np.ndarray) -> np.ndarray:
        """Remove noise with Non-Local Means Denoising."""
        return cv2.fastNlMeansDenoising(gray, h=10, templateWindowSize=7, searchWindowSize=21)

    @staticmethod
    def _binarize(gray: np.ndarray) -> np.ndarray:
        """Adaptive thresholding to produce a clean binary image."""
        return cv2.adaptiveThreshold(
            gray, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            blockSize=31,
            C=11,
        )

    def preprocess_image(self, image: Image.Image) -> Image.Image:
        """Full FR-201 preprocessing pipeline.

        1. Resolution normalisation to 300 DPI
        2. Grayscale conversion
        3. Deskewing via minAreaRect
        4. Non-local-means denoising
        5. Adaptive binarisation
        """
        # Step 1: normalise resolution
        image = self._normalize_resolution(image)

        # Step 2: convert to OpenCV grayscale
        cv_img = self._pil_to_cv2(image)
        if len(cv_img.shape) == 3:
            gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)
        else:
            gray = cv_img

        # Step 3: deskew
        gray = self._deskew(gray)

        # Step 4: denoise
        gray = self._denoise(gray)

        # Step 5: binarize
        binary = self._binarize(gray)

        return self._cv2_to_pil(binary)

    # ------------------------------------------------------------------
    # FR-202  Dual-engine OCR with confidence-weighted merging
    # ------------------------------------------------------------------

    def _get_easyocr_reader(self, langs: List[str]) -> Any:
        """Return a cached EasyOCR Reader for the requested languages."""
        key = tuple(sorted(langs))
        if key not in self._easyocr_readers:
            self._easyocr_readers[key] = easyocr.Reader(list(key), gpu=False)
        return self._easyocr_readers[key]

    def _run_tesseract(self, processed: Image.Image, lang: str = "en") -> Tuple[str, float]:
        """Run Tesseract and return (text, confidence 0-100)."""
        tess_lang = _TESSERACT_LANG_MAP.get(lang, "eng")

        data = pytesseract.image_to_data(
            processed, lang=tess_lang, output_type=pytesseract.Output.DICT,
        )
        confidences = [int(c) for c in data["conf"] if int(c) > 0]
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0

        text = pytesseract.image_to_string(processed, lang=tess_lang)
        return text, avg_confidence

    def _run_easyocr(self, processed: Image.Image, lang: str = "en") -> Tuple[str, float]:
        """Run EasyOCR and return (text, confidence 0-100).

        Raises RuntimeError if EasyOCR is unavailable.
        """
        if not _EASYOCR_AVAILABLE:
            raise RuntimeError("EasyOCR is not installed")

        easy_lang = _EASYOCR_LANG_MAP.get(lang, "en")
        reader = self._get_easyocr_reader([easy_lang])

        img_array = np.array(processed)
        results = reader.readtext(img_array)

        if not results:
            return "", 0.0

        texts: List[str] = []
        confs: List[float] = []
        for _bbox, text, conf in results:
            texts.append(text)
            confs.append(conf)

        full_text = " ".join(texts)
        # EasyOCR confidence is 0-1; convert to 0-100
        avg_confidence = (sum(confs) / len(confs)) * 100.0 if confs else 0.0
        return full_text, avg_confidence

    @staticmethod
    def _merge_ocr_results(
        tess_text: str, tess_conf: float,
        easy_text: str, easy_conf: float,
    ) -> Tuple[str, float]:
        """Confidence-weighted merge of two OCR engine outputs.

        Strategy:
        * If one engine has substantially higher confidence (>15 pts), prefer it
          outright, since merging low-quality text just adds noise.
        * Otherwise return the text from the engine with higher confidence,
          but report the weighted-average confidence.

        The *raw* outputs from both engines are still kept in the final JSON
        (FR-206) so downstream consumers can inspect them.
        """
        if tess_conf <= 0 and easy_conf <= 0:
            return tess_text or easy_text, 0.0

        total = tess_conf + easy_conf
        if total == 0:
            total = 1.0  # avoid division by zero

        weighted_conf = (
            (tess_conf * tess_conf + easy_conf * easy_conf) / total
        )

        # Pick the better text; fall back to Tesseract when confidence is close
        if easy_conf - tess_conf > 15:
            merged_text = easy_text
        else:
            merged_text = tess_text

        return merged_text, weighted_conf

    def extract_text(
        self, image: Image.Image, lang: str = "en",
    ) -> Tuple[str, float, Dict[str, Any]]:
        """Extract text from image using the dual-engine pipeline.

        Returns:
            (merged_text, merged_confidence, engine_details)
        """
        processed = self.preprocess_image(image)

        # -- Tesseract (always available) --------------------------------
        tess_text, tess_conf = self._run_tesseract(processed, lang=lang)

        engine_details: Dict[str, Any] = {
            "tesseract": {"text": tess_text, "confidence": round(tess_conf, 2)},
        }

        # -- EasyOCR (optional) ------------------------------------------
        easy_text, easy_conf = "", 0.0
        if _EASYOCR_AVAILABLE:
            try:
                easy_text, easy_conf = self._run_easyocr(processed, lang=lang)
                engine_details["easyocr"] = {
                    "text": easy_text,
                    "confidence": round(easy_conf, 2),
                }
            except Exception as exc:  # noqa: BLE001
                logger.warning("EasyOCR failed, falling back to Tesseract only: %s", exc)

        # -- Merge -------------------------------------------------------
        if easy_text:
            merged_text, merged_conf = self._merge_ocr_results(
                tess_text, tess_conf, easy_text, easy_conf,
            )
            engine_details["merge_strategy"] = "confidence_weighted"
        else:
            merged_text, merged_conf = tess_text, tess_conf
            engine_details["merge_strategy"] = "tesseract_only"

        return merged_text, merged_conf, engine_details

    # ------------------------------------------------------------------
    # Field parsing helpers
    # ------------------------------------------------------------------

    def parse_amount(self, amount_str: str) -> Optional[float]:
        """Parse amount string to float."""
        try:
            cleaned = amount_str.replace(",", "").strip()
            return float(cleaned)
        except (ValueError, AttributeError):
            return None

    def parse_date(self, date_str: str) -> Optional[datetime]:
        """Parse date string to datetime."""
        date_str = date_str.strip()
        for fmt in self.DATE_FORMATS:
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue
        return None

    def extract_field(self, text: str, field: str) -> Optional[str]:
        """Extract a specific field from OCR text using regex patterns."""
        patterns = self.PATTERNS.get(field, [])
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
            if match:
                # Some payment_terms patterns have no capture group
                try:
                    return match.group(1).strip()
                except IndexError:
                    return match.group(0).strip()
        return None

    def _normalise_currency(self, raw: Optional[str]) -> Optional[str]:
        """Map a raw currency symbol/code to an ISO 4217 code."""
        if raw is None:
            return None
        raw = raw.strip()
        return self._CURRENCY_SYMBOL_MAP.get(raw, raw.upper() if len(raw) == 3 else None)

    # ------------------------------------------------------------------
    # FR-203  Structured field extraction
    # ------------------------------------------------------------------

    def extract_structured_data(
        self, image: Image.Image, lang: str = "en",
    ) -> Dict[str, Any]:
        """Full OCR pipeline: preprocess, extract text, parse structured data.

        Parameters:
            image: PIL Image of the invoice.
            lang:  ISO 639-1 language code (en, de, fr, es, hi).
                   Defaults to ``"en"`` to maintain backward compatibility.

        Returns:
            Structured dict with all extracted fields, raw text, and engine
            metadata (FR-206).
        """
        raw_text, confidence, engine_details = self.extract_text(image, lang=lang)

        # -- Scalar fields -----------------------------------------------
        invoice_number = self.extract_field(raw_text, "invoice_number")
        date_str = self.extract_field(raw_text, "date")
        due_date_str = self.extract_field(raw_text, "due_date")
        total_str = self.extract_field(raw_text, "total_amount")
        subtotal_str = self.extract_field(raw_text, "subtotal")
        tax_str = self.extract_field(raw_text, "tax")
        vendor_name = self.extract_field(raw_text, "vendor_name")
        buyer_name = self.extract_field(raw_text, "buyer_name")
        currency_raw = self.extract_field(raw_text, "currency")
        payment_terms = self.extract_field(raw_text, "payment_terms")

        # -- Parse amounts -----------------------------------------------
        total_amount = self.parse_amount(total_str) if total_str else None
        subtotal = self.parse_amount(subtotal_str) if subtotal_str else None
        tax_amount = self.parse_amount(tax_str) if tax_str else None

        # -- Parse dates -------------------------------------------------
        invoice_date = self.parse_date(date_str) if date_str else None
        due_date = self.parse_date(due_date_str) if due_date_str else None

        # -- Currency normalisation --------------------------------------
        currency = self._normalise_currency(currency_raw)

        # -- Line items --------------------------------------------------
        line_items = self._extract_line_items(raw_text)

        # -- Build FR-206 structured JSON output -------------------------
        result: Dict[str, Any] = {
            # Core extracted & parsed fields
            "invoice_number": invoice_number,
            "invoice_date": invoice_date,
            "due_date": due_date,
            "vendor_name": vendor_name,
            "buyer_name": buyer_name,
            "total_amount": total_amount,
            "subtotal": subtotal,
            "tax_amount": tax_amount,
            "currency": currency,
            "payment_terms": payment_terms,
            "line_items": line_items,

            # OCR metadata
            "ocr_confidence": round(confidence, 2),
            "ocr_engines": engine_details,
            "language": lang,

            # Raw OCR text (FR-206)
            "raw_text": raw_text,

            # Raw extracted strings for downstream inspection
            "extracted_fields": {
                "raw_invoice_number": invoice_number,
                "raw_date": date_str,
                "raw_due_date": due_date_str,
                "raw_total": total_str,
                "raw_subtotal": subtotal_str,
                "raw_tax": tax_str,
                "raw_vendor": vendor_name,
                "raw_buyer": buyer_name,
                "raw_currency": currency_raw,
                "raw_payment_terms": payment_terms,
            },
        }

        logger.info(
            "OCR extracted: inv#%s, total=%s, currency=%s, confidence=%.1f%%, engine=%s",
            invoice_number, total_amount, currency, confidence,
            engine_details.get("merge_strategy", "unknown"),
        )
        return result

    # ------------------------------------------------------------------
    # Line-item extraction
    # ------------------------------------------------------------------

    def _extract_line_items(self, text: str) -> List[Dict[str, Any]]:
        """Attempt to extract line items from invoice text.

        Tries several common tabular formats:
        * qty  description  unit_price  total
        * description  qty  unit_price  total
        """
        items: List[Dict[str, Any]] = []

        # Pattern 1: quantity first
        line_pattern_qty_first = (
            r"(\d+)\s+(.+?)\s+[\$\u20ac\u00a3\u20b9]?([\d,]+\.?\d{0,2})"
            r"\s+[\$\u20ac\u00a3\u20b9]?([\d,]+\.?\d{0,2})"
        )
        # Pattern 2: description first, then qty, unit price, total
        line_pattern_desc_first = (
            r"([A-Za-z][\w\s]{2,40}?)\s+(\d+)\s+"
            r"[\$\u20ac\u00a3\u20b9]?([\d,]+\.?\d{0,2})\s+"
            r"[\$\u20ac\u00a3\u20b9]?([\d,]+\.?\d{0,2})"
        )

        # Try quantity-first pattern
        for match in re.finditer(line_pattern_qty_first, text):
            try:
                items.append({
                    "quantity": int(match.group(1)),
                    "description": match.group(2).strip(),
                    "unit_price": float(match.group(3).replace(",", "")),
                    "total": float(match.group(4).replace(",", "")),
                })
            except (ValueError, IndexError):
                continue

        # If nothing found, try description-first pattern
        if not items:
            for match in re.finditer(line_pattern_desc_first, text):
                try:
                    items.append({
                        "quantity": int(match.group(2)),
                        "description": match.group(1).strip(),
                        "unit_price": float(match.group(3).replace(",", "")),
                        "total": float(match.group(4).replace(",", "")),
                    })
                except (ValueError, IndexError):
                    continue

        return items


# ---------------------------------------------------------------------------
# Singleton (backward compatible)
# ---------------------------------------------------------------------------
ocr_service = OCRService()
