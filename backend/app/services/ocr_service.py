"""
OCR Service - Extract structured data from invoice images/PDFs
Uses Tesseract OCR with pre/post-processing for accuracy
"""
import re
import io
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List
from PIL import Image, ImageEnhance, ImageFilter
import pytesseract
import numpy as np

logger = logging.getLogger(__name__)


class OCRService:
    """Extract structured data from invoice documents using Tesseract OCR."""

    # Common invoice field patterns
    PATTERNS = {
        "invoice_number": [
            r"(?:invoice\s*(?:#|no\.?|number)\s*[:.]?\s*)([A-Z0-9\-\/]+)",
            r"(?:inv\s*(?:#|no\.?)\s*[:.]?\s*)([A-Z0-9\-\/]+)",
            r"(?:#\s*)(\d{4,})",
        ],
        "date": [
            r"(?:invoice\s*date|date\s*of\s*invoice|date)\s*[:.]?\s*(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})",
            r"(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{2,4})",
            r"(\d{4}-\d{2}-\d{2})",
        ],
        "due_date": [
            r"(?:due\s*date|payment\s*due|pay\s*by)\s*[:.]?\s*(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})",
            r"(?:due\s*date|payment\s*due)\s*[:.]?\s*(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{2,4})",
        ],
        "total_amount": [
            r"(?:total\s*(?:amount|due|payable)?)\s*[:.]?\s*\$?\s*([\d,]+\.?\d{0,2})",
            r"(?:grand\s*total|amount\s*due|balance\s*due)\s*[:.]?\s*\$?\s*([\d,]+\.?\d{0,2})",
            r"(?:total)\s*\$?\s*([\d,]+\.\d{2})",
        ],
        "subtotal": [
            r"(?:sub\s*total|subtotal)\s*[:.]?\s*\$?\s*([\d,]+\.?\d{0,2})",
        ],
        "tax": [
            r"(?:tax|vat|gst|sales\s*tax)\s*[:.]?\s*\$?\s*([\d,]+\.?\d{0,2})",
            r"(?:tax)\s*\(?\d*\.?\d*%?\)?\s*[:.]?\s*\$?\s*([\d,]+\.?\d{0,2})",
        ],
        "vendor_name": [
            r"(?:from|vendor|supplier|bill\s*from|sold\s*by)\s*[:.]?\s*([A-Z][A-Za-z\s&\.,]+?)(?:\n|$)",
        ],
        "buyer_name": [
            r"(?:to|bill\s*to|sold\s*to|customer|client)\s*[:.]?\s*([A-Z][A-Za-z\s&\.,]+?)(?:\n|$)",
        ],
    }

    DATE_FORMATS = [
        "%m/%d/%Y", "%d/%m/%Y", "%m-%d-%Y", "%d-%m-%Y",
        "%m.%d.%Y", "%d.%m.%Y", "%Y-%m-%d",
        "%d %B %Y", "%d %b %Y", "%B %d, %Y", "%b %d, %Y",
        "%m/%d/%y", "%d/%m/%y",
    ]

    def preprocess_image(self, image: Image.Image) -> Image.Image:
        """Enhance image for better OCR accuracy."""
        # Convert to grayscale
        img = image.convert("L")
        
        # Increase contrast
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(2.0)
        
        # Sharpen
        img = img.filter(ImageFilter.SHARPEN)
        
        # Denoise
        img_array = np.array(img)
        
        # Adaptive thresholding simulation
        threshold = np.mean(img_array)
        img_array = ((img_array > threshold) * 255).astype(np.uint8)
        
        return Image.fromarray(img_array)

    def extract_text(self, image: Image.Image) -> tuple[str, float]:
        """Extract text from image with confidence score."""
        # Preprocess
        processed = self.preprocess_image(image)
        
        # Get detailed OCR data
        data = pytesseract.image_to_data(processed, output_type=pytesseract.Output.DICT)
        
        # Calculate confidence
        confidences = [int(c) for c in data["conf"] if int(c) > 0]
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0
        
        # Get full text
        text = pytesseract.image_to_string(processed)
        
        return text, avg_confidence

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
                return match.group(1).strip()
        return None

    def extract_structured_data(self, image: Image.Image) -> Dict[str, Any]:
        """Full OCR pipeline: extract text and parse structured invoice data."""
        raw_text, confidence = self.extract_text(image)
        
        # Extract fields
        invoice_number = self.extract_field(raw_text, "invoice_number")
        date_str = self.extract_field(raw_text, "date")
        due_date_str = self.extract_field(raw_text, "due_date")
        total_str = self.extract_field(raw_text, "total_amount")
        subtotal_str = self.extract_field(raw_text, "subtotal")
        tax_str = self.extract_field(raw_text, "tax")
        vendor_name = self.extract_field(raw_text, "vendor_name")
        buyer_name = self.extract_field(raw_text, "buyer_name")
        
        # Parse amounts
        total_amount = self.parse_amount(total_str) if total_str else None
        subtotal = self.parse_amount(subtotal_str) if subtotal_str else None
        tax_amount = self.parse_amount(tax_str) if tax_str else None
        
        # Parse dates
        invoice_date = self.parse_date(date_str) if date_str else None
        due_date = self.parse_date(due_date_str) if due_date_str else None
        
        # Extract line items (attempt)
        line_items = self._extract_line_items(raw_text)
        
        result = {
            "raw_text": raw_text,
            "ocr_confidence": round(confidence, 2),
            "invoice_number": invoice_number,
            "invoice_date": invoice_date,
            "due_date": due_date,
            "vendor_name": vendor_name,
            "buyer_name": buyer_name,
            "total_amount": total_amount,
            "subtotal": subtotal,
            "tax_amount": tax_amount,
            "line_items": line_items,
            "extracted_fields": {
                "raw_invoice_number": invoice_number,
                "raw_date": date_str,
                "raw_due_date": due_date_str,
                "raw_total": total_str,
                "raw_subtotal": subtotal_str,
                "raw_tax": tax_str,
                "raw_vendor": vendor_name,
                "raw_buyer": buyer_name,
            }
        }
        
        logger.info(f"OCR extracted: inv#{invoice_number}, total={total_amount}, confidence={confidence:.1f}%")
        return result

    def _extract_line_items(self, text: str) -> List[Dict[str, Any]]:
        """Attempt to extract line items from invoice text."""
        items = []
        # Pattern: quantity, description, unit price, total
        line_pattern = r"(\d+)\s+(.+?)\s+\$?([\d,]+\.?\d{0,2})\s+\$?([\d,]+\.?\d{0,2})"
        
        for match in re.finditer(line_pattern, text):
            try:
                items.append({
                    "quantity": int(match.group(1)),
                    "description": match.group(2).strip(),
                    "unit_price": float(match.group(3).replace(",", "")),
                    "total": float(match.group(4).replace(",", "")),
                })
            except (ValueError, IndexError):
                continue
        
        return items


# Singleton
ocr_service = OCRService()
