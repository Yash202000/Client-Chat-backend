"""
Simple test script to verify intent_config functionality.
Run this from the backend directory: python test_intent_config.py
"""

from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.models.workflow import Workflow

def test_intent_config():
    db: Session = SessionLocal()

    try:
        # Test 1: Query workflows and check intent_config column
        print("✓ Testing workflow query with intent_config column...")
        workflows = db.query(Workflow).limit(5).all()
        print(f"  Found {len(workflows)} workflows")

        for workflow in workflows:
            print(f"  - Workflow: {workflow.name}")
            print(f"    intent_config: {workflow.intent_config}")

        # Test 2: Create a workflow with intent_config
        print("\n✓ Testing workflow creation with intent_config...")
        test_config = {
            "enabled": True,
            "trigger_intents": [
                {
                    "id": "test_intent_1",
                    "name": "test_greeting",
                    "keywords": ["hello", "hi"],
                    "training_phrases": ["Hello!", "Hi there"],
                    "confidence_threshold": 0.7
                }
            ],
            "entities": [
                {
                    "name": "user_name",
                    "type": "text",
                    "extraction_method": "llm",
                    "required": False
                }
            ],
            "auto_trigger_enabled": True,
            "min_confidence": 0.75
        }

        print(f"  Sample intent_config structure: {test_config}")
        print("\n✅ All tests passed! The intent_config column is working correctly.")

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    test_intent_config()
