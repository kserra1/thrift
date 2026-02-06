"""
Train a simple Iris classifier for testing.
This is just for development - real users would bring their own models.
"""
from sklearn.datasets import load_iris
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score
import joblib

# Load data
X, y = load_iris(return_X_y=True)
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42
)

# Train model
model = RandomForestClassifier(n_estimators=100, random_state=42)
model.fit(X_train, y_train)

# Evaluate
y_pred = model.predict(X_test)
accuracy = accuracy_score(y_test, y_pred)
print(f"Model accuracy: {accuracy:.2%}")

output_path = 'iris_v1.pkl'

# Save
joblib.dump(model, output_path)
print(f"Model saved to {output_path}")
print(f"\nNext steps:")
print(f"  1. Register: python scripts/register_model.py --model-path {output_path} --name iris --version v1")
print(f"  2. Serve:    MODEL_NAME=iris MODEL_VERSION=v1 uvicorn workers.app.main:app")
