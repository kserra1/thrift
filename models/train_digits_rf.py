"""
Train a larger digits classifier for more realistic load testing.
This model is heavier than iris and is useful for throughput/latency experiments.
"""
from sklearn.datasets import load_digits
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score
import joblib
import json

# Load data
X, y = load_digits(return_X_y=True)
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42
)

# Train model (heavier than iris)
model = RandomForestClassifier(
    n_estimators=400,
    max_depth=None,
    n_jobs=1,
    random_state=42
)
model.fit(X_train, y_train)

# Evaluate
y_pred = model.predict(X_test)
accuracy = accuracy_score(y_test, y_pred)
print(f"Model accuracy: {accuracy:.2%}")

output_path = "digits_v1.pkl"
joblib.dump(model, output_path)
print(f"Model saved to {output_path}")

# Print a sample payload for testing
sample_features = X_test[0].tolist()
print("\nSample predict payload:")
print(json.dumps({"features": sample_features}))

print(f"\nNext steps:")
print(f"  1. Register: python scripts/register_model.py --model-path {output_path} --name digits --version v1")
print(f"  2. Load:     curl -sS -X POST http://localhost:8080/models/load -H 'Content-Type: application/json' -d '{{\"model_name\":\"digits\",\"version\":\"v1\",\"batch_size\":32,\"batch_wait_ms\":10}}'")
