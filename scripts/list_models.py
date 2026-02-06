"""
CLI tool to list registered models.
Usage: python scripts/list_models.py
"""
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from workers.app.database import SessionLocal, ModelMetadata, init_db


def list_models():
    """List all registered models."""
    init_db()
    db = SessionLocal()
    try:
        models = db.query(ModelMetadata).order_by(
            ModelMetadata.model_name,
            ModelMetadata.created_at.desc()
        ).all()
        
        if not models:
            print("No models registered yet.")
            return
        
        print(f"\n{'Name':<20} {'Version':<12} {'Framework':<12} {'Created':<20} {'S3 Path'}")
        print("=" * 100)
        
        for model in models:
            created = model.created_at.strftime("%Y-%m-%d %H:%M:%S")
            print(f"{model.model_name:<20} {model.version:<12} {model.framework:<12} {created:<20} {model.s3_path}")
            if model.model_metadata:  # Changed from 'metadata'
                print(f"  └─ Metadata: {model.model_metadata}")
        
        print()
        
    finally:
        db.close()


if __name__ == "__main__":
    list_models()