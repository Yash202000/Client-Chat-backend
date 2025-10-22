from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from app.core.dependencies import get_db, get_current_user
from app.models.intent import Intent, Entity, IntentMatch, intent_entities
from app.models.user import User
from app.schemas.intent import (
    IntentCreate, IntentUpdate, IntentResponse, IntentWithEntities,
    EntityCreate, EntityUpdate, EntityResponse,
    TestIntentRequest, TestIntentResponse,
    IntentMatchResponse
)
from app.services.intent_service import IntentService

router = APIRouter()


# ============================================================================
# INTENT ENDPOINTS
# ============================================================================

@router.post("/", response_model=IntentResponse)
def create_intent(
    intent: IntentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new intent"""

    # Verify company access
    if current_user.company_id != intent.company_id:
        raise HTTPException(status_code=403, detail="Not authorized to create intents for this company")

    # Create intent
    db_intent = Intent(
        company_id=intent.company_id,
        name=intent.name,
        description=intent.description,
        intent_category=intent.intent_category,
        training_phrases=intent.training_phrases,
        keywords=intent.keywords,
        trigger_workflow_id=intent.trigger_workflow_id,
        auto_trigger_enabled=intent.auto_trigger_enabled,
        require_agent_approval=intent.require_agent_approval,
        confidence_threshold=intent.confidence_threshold,
        min_confidence_auto_trigger=intent.min_confidence_auto_trigger,
        priority=intent.priority
    )

    db.add(db_intent)
    db.commit()
    db.refresh(db_intent)

    # Associate entities
    if intent.entity_ids:
        for entity_id in intent.entity_ids:
            entity = db.query(Entity).filter(
                Entity.id == entity_id,
                Entity.company_id == intent.company_id
            ).first()
            if entity:
                db_intent.entities.append(entity)

        db.commit()
        db.refresh(db_intent)

    return db_intent


@router.get("/", response_model=List[IntentWithEntities])
def list_intents(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List all intents for the current user's company"""

    intents = db.query(Intent).filter(
        Intent.company_id == current_user.company_id
    ).offset(skip).limit(limit).all()

    return intents


@router.get("/{intent_id}", response_model=IntentWithEntities)
def get_intent(
    intent_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get a specific intent"""

    intent = db.query(Intent).filter(
        Intent.id == intent_id,
        Intent.company_id == current_user.company_id
    ).first()

    if not intent:
        raise HTTPException(status_code=404, detail="Intent not found")

    return intent


@router.put("/{intent_id}", response_model=IntentResponse)
def update_intent(
    intent_id: int,
    intent_update: IntentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update an intent"""

    db_intent = db.query(Intent).filter(
        Intent.id == intent_id,
        Intent.company_id == current_user.company_id
    ).first()

    if not db_intent:
        raise HTTPException(status_code=404, detail="Intent not found")

    # Update fields
    update_data = intent_update.dict(exclude_unset=True)
    entity_ids = update_data.pop("entity_ids", None)

    for field, value in update_data.items():
        setattr(db_intent, field, value)

    # Update entity associations
    if entity_ids is not None:
        db_intent.entities.clear()
        for entity_id in entity_ids:
            entity = db.query(Entity).filter(
                Entity.id == entity_id,
                Entity.company_id == current_user.company_id
            ).first()
            if entity:
                db_intent.entities.append(entity)

    db.commit()
    db.refresh(db_intent)

    return db_intent


@router.delete("/{intent_id}")
def delete_intent(
    intent_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete an intent"""

    db_intent = db.query(Intent).filter(
        Intent.id == intent_id,
        Intent.company_id == current_user.company_id
    ).first()

    if not db_intent:
        raise HTTPException(status_code=404, detail="Intent not found")

    db.delete(db_intent)
    db.commit()

    return {"status": "deleted", "id": intent_id}


@router.post("/{intent_id}/test", response_model=TestIntentResponse)
async def test_intent(
    intent_id: int,
    request: TestIntentRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Test intent detection with a sample message"""

    db_intent = db.query(Intent).filter(
        Intent.id == intent_id,
        Intent.company_id == current_user.company_id
    ).first()

    if not db_intent:
        raise HTTPException(status_code=404, detail="Intent not found")

    # Use IntentService to test
    intent_service = IntentService(db)

    # Temporarily create a list with just this intent for testing
    result = await intent_service.detect_intent(
        message=request.test_message,
        company_id=current_user.company_id,
        conversation_id="test_conversation"
    )

    if result:
        intent, confidence, entities, matched_method = result

        if intent.id == intent_id:
            return TestIntentResponse(
                matched=True,
                intent_id=intent.id,
                intent_name=intent.name,
                confidence=confidence,
                matched_method=matched_method,
                extracted_entities=entities,
                reasoning=f"Matched using {matched_method} method"
            )

    return TestIntentResponse(
        matched=False,
        confidence=0.0,
        reasoning="Intent did not match the test message"
    )


@router.get("/{intent_id}/matches", response_model=List[IntentMatchResponse])
def get_intent_matches(
    intent_id: int,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all matches for a specific intent"""

    # Verify intent belongs to user's company
    intent = db.query(Intent).filter(
        Intent.id == intent_id,
        Intent.company_id == current_user.company_id
    ).first()

    if not intent:
        raise HTTPException(status_code=404, detail="Intent not found")

    # Get matches
    matches = db.query(IntentMatch).filter(
        IntentMatch.intent_id == intent_id
    ).order_by(IntentMatch.matched_at.desc()).offset(skip).limit(limit).all()

    # Add intent name to response
    result = []
    for match in matches:
        match_dict = {
            "id": match.id,
            "conversation_id": match.conversation_id,
            "intent_id": match.intent_id,
            "intent_name": intent.name,
            "message_text": match.message_text,
            "confidence_score": match.confidence_score,
            "matched_method": match.matched_method,
            "extracted_entities": match.extracted_entities,
            "triggered_workflow_id": match.triggered_workflow_id,
            "workflow_executed": match.workflow_executed,
            "execution_status": match.execution_status,
            "matched_at": match.matched_at
        }
        result.append(IntentMatchResponse(**match_dict))

    return result


# ============================================================================
# ENTITY ENDPOINTS
# ============================================================================

@router.post("/entities", response_model=EntityResponse)
def create_entity(
    entity: EntityCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new entity"""

    if current_user.company_id != entity.company_id:
        raise HTTPException(status_code=403, detail="Not authorized")

    db_entity = Entity(
        company_id=entity.company_id,
        name=entity.name,
        description=entity.description,
        entity_type=entity.entity_type,
        extraction_method=entity.extraction_method,
        validation_regex=entity.validation_regex,
        example_values=entity.example_values
    )

    db.add(db_entity)
    db.commit()
    db.refresh(db_entity)

    return db_entity


@router.get("/entities", response_model=List[EntityResponse])
def list_entities(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List all entities for the current user's company"""

    entities = db.query(Entity).filter(
        Entity.company_id == current_user.company_id
    ).offset(skip).limit(limit).all()

    return entities


@router.put("/entities/{entity_id}", response_model=EntityResponse)
def update_entity(
    entity_id: int,
    entity_update: EntityUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update an entity"""

    db_entity = db.query(Entity).filter(
        Entity.id == entity_id,
        Entity.company_id == current_user.company_id
    ).first()

    if not db_entity:
        raise HTTPException(status_code=404, detail="Entity not found")

    update_data = entity_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_entity, field, value)

    db.commit()
    db.refresh(db_entity)

    return db_entity


@router.delete("/entities/{entity_id}")
def delete_entity(
    entity_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete an entity"""

    db_entity = db.query(Entity).filter(
        Entity.id == entity_id,
        Entity.company_id == current_user.company_id
    ).first()

    if not db_entity:
        raise HTTPException(status_code=404, detail="Entity not found")

    db.delete(db_entity)
    db.commit()

    return {"status": "deleted", "id": entity_id}
