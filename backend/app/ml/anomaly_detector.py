"""
Anomaly Detection ML Models
- Isolation Forest for statistical anomaly detection
- Autoencoder for deep anomaly detection
"""
import logging
import pickle
from typing import Dict, Any, List, Optional
import numpy as np

logger = logging.getLogger(__name__)

# scikit-learn imports
try:
    from sklearn.ensemble import IsolationForest
    from sklearn.preprocessing import StandardScaler
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False

# PyTorch imports
try:
    import torch
    import torch.nn as nn
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False


class InvoiceAnomalyDetector:
    """Detect anomalous invoices using Isolation Forest and Autoencoder."""

    FEATURE_NAMES = [
        "total_amount", "tax_amount", "subtotal",
        "amount_tax_ratio", "amount_per_item",
        "day_of_week", "day_of_month", "month",
        "days_until_due", "ocr_confidence",
        "text_length", "vendor_frequency",
        "amount_deviation_from_vendor_mean",
    ]

    def __init__(self):
        self.isolation_forest = None
        self.scaler = StandardScaler() if SKLEARN_AVAILABLE else None
        self.autoencoder = None
        self.is_trained = False
        self._init_models()

    def _init_models(self):
        """Initialize ML models."""
        if SKLEARN_AVAILABLE:
            self.isolation_forest = IsolationForest(
                n_estimators=200,
                contamination=0.1,  # Expected fraud rate
                max_samples="auto",
                random_state=42,
                n_jobs=-1,
            )
            logger.info("Isolation Forest initialized")

        if TORCH_AVAILABLE:
            self.autoencoder = InvoiceAutoencoder(
                input_dim=len(self.FEATURE_NAMES)
            )
            logger.info("Autoencoder initialized")

    def extract_features(self, invoice_data: Dict[str, Any]) -> np.ndarray:
        """Extract numerical features from invoice data for anomaly detection."""
        features = []

        # Amount features
        total = float(invoice_data.get("total_amount", 0) or 0)
        tax = float(invoice_data.get("tax_amount", 0) or 0)
        subtotal = float(invoice_data.get("subtotal", 0) or 0)
        
        features.append(total)
        features.append(tax)
        features.append(subtotal)
        
        # Ratio features
        features.append(tax / total if total > 0 else 0)  # tax ratio
        
        line_items = invoice_data.get("line_items", [])
        items_count = len(line_items) if line_items else 1
        features.append(total / items_count)  # amount per item

        # Date features
        invoice_date = invoice_data.get("invoice_date")
        if invoice_date:
            features.append(float(invoice_date.weekday()))
            features.append(float(invoice_date.day))
            features.append(float(invoice_date.month))
        else:
            features.extend([0.0, 0.0, 0.0])

        # Due date proximity
        due_date = invoice_data.get("due_date")
        if invoice_date and due_date:
            features.append(float((due_date - invoice_date).days))
        else:
            features.append(30.0)  # Default 30 days

        # OCR confidence
        features.append(float(invoice_data.get("ocr_confidence", 50) or 50))

        # Text features
        raw_text = invoice_data.get("raw_text", "")
        features.append(float(len(raw_text)))

        # Vendor frequency (populated externally)
        features.append(float(invoice_data.get("vendor_frequency", 1)))

        # Amount deviation from vendor mean (populated externally)
        features.append(float(invoice_data.get("amount_deviation", 0)))

        return np.array(features, dtype=np.float32)

    def train(self, historical_data: List[Dict[str, Any]]):
        """Train models on historical invoice data."""
        if not historical_data:
            logger.warning("No training data provided")
            return

        # Extract features
        X = np.array([self.extract_features(inv) for inv in historical_data])
        
        # Scale features
        if self.scaler:
            X_scaled = self.scaler.fit_transform(X)
        else:
            X_scaled = X

        # Train Isolation Forest
        if self.isolation_forest:
            self.isolation_forest.fit(X_scaled)
            logger.info(f"Isolation Forest trained on {len(X)} samples")

        # Train Autoencoder
        if self.autoencoder and TORCH_AVAILABLE:
            self._train_autoencoder(X_scaled)

        self.is_trained = True

    def _train_autoencoder(self, X: np.ndarray, epochs: int = 100, lr: float = 0.001):
        """Train the autoencoder on normal invoice data."""
        tensor_data = torch.FloatTensor(X)
        dataset = torch.utils.data.TensorDataset(tensor_data, tensor_data)
        loader = torch.utils.data.DataLoader(dataset, batch_size=32, shuffle=True)

        optimizer = torch.optim.Adam(self.autoencoder.parameters(), lr=lr)
        criterion = nn.MSELoss()

        self.autoencoder.train()
        for epoch in range(epochs):
            total_loss = 0
            for batch_x, _ in loader:
                optimizer.zero_grad()
                reconstructed = self.autoencoder(batch_x)
                loss = criterion(reconstructed, batch_x)
                loss.backward()
                optimizer.step()
                total_loss += loss.item()

            if (epoch + 1) % 20 == 0:
                avg_loss = total_loss / len(loader)
                logger.info(f"Autoencoder epoch {epoch+1}/{epochs}, loss: {avg_loss:.6f}")

    def detect_anomaly(self, invoice_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Detect anomalies in a single invoice.
        Returns anomaly score and details.
        """
        features = self.extract_features(invoice_data)
        
        results = {
            "anomaly_score": 0.0,
            "is_anomalous": False,
            "isolation_forest": None,
            "autoencoder": None,
            "feature_importance": {},
        }

        scores = []

        # Isolation Forest prediction
        if self.isolation_forest and self.is_trained:
            features_scaled = self.scaler.transform(features.reshape(1, -1))
            
            # Get anomaly score (-1 = anomaly, 1 = normal)
            prediction = self.isolation_forest.predict(features_scaled)[0]
            # Score function: lower = more anomalous
            if_score = -self.isolation_forest.score_samples(features_scaled)[0]
            
            # Normalize to 0-100
            if_normalized = min(100, max(0, if_score * 50))
            
            results["isolation_forest"] = {
                "prediction": "anomaly" if prediction == -1 else "normal",
                "raw_score": round(float(if_score), 4),
                "normalized_score": round(if_normalized, 2),
            }
            scores.append(if_normalized)

        # Autoencoder prediction
        if self.autoencoder and self.is_trained and TORCH_AVAILABLE:
            features_scaled = self.scaler.transform(features.reshape(1, -1))
            tensor = torch.FloatTensor(features_scaled)
            
            self.autoencoder.eval()
            with torch.no_grad():
                reconstructed = self.autoencoder(tensor)
                reconstruction_error = torch.mean((tensor - reconstructed) ** 2).item()
            
            # Normalize reconstruction error to 0-100
            ae_normalized = min(100, reconstruction_error * 100)
            
            results["autoencoder"] = {
                "reconstruction_error": round(reconstruction_error, 6),
                "normalized_score": round(ae_normalized, 2),
            }
            scores.append(ae_normalized)

        # If models not trained, use heuristic scoring
        if not self.is_trained:
            heuristic_score = self._heuristic_anomaly_score(invoice_data, features)
            scores.append(heuristic_score)
            results["heuristic"] = {
                "score": round(heuristic_score, 2),
                "note": "Using heuristic scoring (models not yet trained)"
            }

        # Combined score
        if scores:
            results["anomaly_score"] = round(sum(scores) / len(scores), 2)
            results["is_anomalous"] = results["anomaly_score"] > 50

        # Feature importance
        results["feature_importance"] = self._analyze_feature_importance(
            invoice_data, features
        )

        return results

    def _heuristic_anomaly_score(
        self, invoice_data: Dict, features: np.ndarray
    ) -> float:
        """Fallback heuristic scoring when ML models aren't trained."""
        score = 0
        reasons = []

        total = float(invoice_data.get("total_amount", 0) or 0)
        tax = float(invoice_data.get("tax_amount", 0) or 0)

        # Round number amounts are suspicious
        if total > 0 and total == int(total) and total > 1000:
            score += 15
            reasons.append("Round number amount")

        # Unusual tax rates
        if total > 0 and tax > 0:
            tax_rate = tax / total
            if tax_rate > 0.3 or tax_rate < 0.01:
                score += 20
                reasons.append(f"Unusual tax rate: {tax_rate:.2%}")

        # Very high amounts
        if total > 100000:
            score += 15
            reasons.append(f"High amount: ${total:,.2f}")

        # Low OCR confidence
        ocr_conf = float(invoice_data.get("ocr_confidence", 100) or 100)
        if ocr_conf < 60:
            score += 15
            reasons.append(f"Low OCR confidence: {ocr_conf:.1f}%")

        # Missing critical fields
        missing = []
        for field in ["invoice_number", "vendor_name", "total_amount"]:
            if not invoice_data.get(field):
                missing.append(field)
                score += 10
        if missing:
            reasons.append(f"Missing fields: {', '.join(missing)}")

        return min(100, score)

    def _analyze_feature_importance(
        self, invoice_data: Dict, features: np.ndarray
    ) -> Dict[str, str]:
        """Analyze which features contribute most to anomaly detection."""
        importance = {}
        
        total = float(invoice_data.get("total_amount", 0) or 0)
        if total > 50000:
            importance["total_amount"] = "high_value"
        
        tax = float(invoice_data.get("tax_amount", 0) or 0)
        if total > 0:
            tax_rate = tax / total
            if tax_rate > 0.25 or (tax_rate < 0.03 and tax_rate > 0):
                importance["tax_ratio"] = "unusual"
        
        ocr = float(invoice_data.get("ocr_confidence", 100) or 100)
        if ocr < 70:
            importance["ocr_confidence"] = "low"
        
        return importance

    def save_models(self, path: str):
        """Save trained models to disk."""
        data = {
            "scaler": self.scaler,
            "isolation_forest": self.isolation_forest,
            "is_trained": self.is_trained,
        }
        with open(f"{path}/anomaly_model.pkl", "wb") as f:
            pickle.dump(data, f)

        if self.autoencoder and TORCH_AVAILABLE:
            torch.save(self.autoencoder.state_dict(), f"{path}/autoencoder_model.pt")

    def load_models(self, path: str):
        """Load trained models from disk."""
        try:
            with open(f"{path}/anomaly_model.pkl", "rb") as f:
                data = pickle.load(f)
                self.scaler = data["scaler"]
                self.isolation_forest = data["isolation_forest"]
                self.is_trained = data["is_trained"]

            if self.autoencoder and TORCH_AVAILABLE:
                self.autoencoder.load_state_dict(
                    torch.load(f"{path}/autoencoder_model.pt")
                )
            
            logger.info("Models loaded successfully")
        except FileNotFoundError:
            logger.warning("No pre-trained models found")


if TORCH_AVAILABLE:
    class InvoiceAutoencoder(nn.Module):
        """Autoencoder for invoice anomaly detection."""

        def __init__(self, input_dim: int = 13):
            super().__init__()
            
            self.encoder = nn.Sequential(
                nn.Linear(input_dim, 32),
                nn.ReLU(),
                nn.Dropout(0.2),
                nn.Linear(32, 16),
                nn.ReLU(),
                nn.Linear(16, 8),
                nn.ReLU(),
            )
            
            self.decoder = nn.Sequential(
                nn.Linear(8, 16),
                nn.ReLU(),
                nn.Linear(16, 32),
                nn.ReLU(),
                nn.Dropout(0.2),
                nn.Linear(32, input_dim),
            )

        def forward(self, x):
            encoded = self.encoder(x)
            decoded = self.decoder(encoded)
            return decoded

        def encode(self, x):
            return self.encoder(x)
else:
    class InvoiceAutoencoder:
        """Placeholder when PyTorch is not available."""
        def __init__(self, *args, **kwargs):
            pass


# Singleton
anomaly_detector = InvoiceAnomalyDetector()
