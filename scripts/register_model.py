"""
CLI tool to register a pre-trained model.
Usage: python scripts/register_model.py --model-path ./my_model.pkl --name iris --version v2
"""
import argparse
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from workers.app.storage import ModelStorage
from workers.app.database import SessionLocal, ModelMetadata, init_db


def register_model(
    model_path: str,
    model_name: str,
    version: str,
    framework: str = "sklearn",
    metadata: dict = None
):
    """Upload model to S3 and register in database."""
    
    if not os.path.exists(model_path):
        raise FileNotFoundError(f"Model file not found: {model_path}")
    
    # Upload to S3
    s3_path = f"{model_name}/{model_name}_{version}.pkl"
    storage = ModelStorage()
    
    print(f"Uploading {model_path} to s3://{storage.bucket}/{s3_path}...")
    storage.upload_model(model_path, s3_path)
    print("✓ Upload complete")
    
    # Register in database
    init_db()
    db = SessionLocal()
    try:
        # Check if this version already exists
        existing = db.query(ModelMetadata).filter(
            ModelMetadata.model_name == model_name,
            ModelMetadata.version == version
        ).first()
        
        if existing:
            print(f"⚠ Model {model_name}:{version} already exists. Updating...")
            existing.s3_path = s3_path
            existing.framework = framework
            existing.model_metadata = metadata or {}  # Changed from 'metadata'
        else:
            model_metadata = ModelMetadata(
                model_name=model_name,
                version=version,
                s3_path=s3_path,
                framework=framework,
                model_metadata=metadata or {}  # Changed from 'metadata'
            )
            db.add(model_metadata)
        
        db.commit()
        print(f"✓ Registered {model_name}:{version} in database")
        print(f"\nTo use this model, start the worker with:")
        print(f"  MODEL_NAME={model_name} MODEL_VERSION={version} uvicorn workers.app.main:app")
        
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Register a pre-trained model")
    parser.add_argument(
        "--model-path",
        required=True,
        help="Path to the model file (e.g., ./my_model.pkl)"
    )
    parser.add_argument(
        "--name",
        required=True,
        help="Model name (e.g., iris, fraud-detector)"
    )
    parser.add_argument(
        "--version",
        required=True,
        help="Model version (e.g., v1, v2, 2024-01-15)"
    )
    parser.add_argument(
        "--framework",
        default="sklearn",
        help="ML framework (sklearn, pytorch, tensorflow, xgboost)"
    )
    parser.add_argument(
        "--metadata",
        help="JSON string with additional metadata (e.g., '{\"accuracy\": 0.95}')"
    )
    
    args = parser.parse_args()
    
    metadata = None
    if args.metadata:
        import json
        metadata = json.loads(args.metadata)
    
    register_model(
        model_path=args.model_path,
        model_name=args.name,
        version=args.version,
        framework=args.framework,
        metadata=metadata
    )