"""
Service for managing workflow triggers.

This service handles the registration and management of workflow triggers
based on the visual workflow nodes.
"""
import json
from typing import List, Optional
from sqlalchemy.orm import Session
from app.models.workflow_trigger import WorkflowTrigger, TriggerChannel
from app.models.workflow import Workflow


def extract_trigger_nodes_from_visual_steps(visual_steps: dict) -> List[dict]:
    """
    Extract trigger nodes from the visual workflow steps.

    Args:
        visual_steps: The visual workflow data containing nodes and edges

    Returns:
        List of trigger node data dictionaries
    """
    if not visual_steps or 'nodes' not in visual_steps:
        return []

    trigger_types = [
        'trigger_websocket',
        'trigger_whatsapp',
        'trigger_telegram',
        'trigger_instagram'
    ]

    trigger_nodes = []
    for node in visual_steps.get('nodes', []):
        if node.get('type') in trigger_types:
            trigger_nodes.append(node)

    return trigger_nodes


def map_trigger_type_to_channel(node_type: str) -> Optional[TriggerChannel]:
    """
    Map visual node type to TriggerChannel enum.

    Args:
        node_type: The node type from visual workflow (e.g., 'trigger_websocket')

    Returns:
        TriggerChannel enum value or None
    """
    mapping = {
        'trigger_websocket': TriggerChannel.WEBSOCKET,
        'trigger_whatsapp': TriggerChannel.WHATSAPP,
        'trigger_telegram': TriggerChannel.TELEGRAM,
        'trigger_instagram': TriggerChannel.INSTAGRAM,
    }
    return mapping.get(node_type)


def sync_workflow_triggers(
    db: Session,
    workflow_id: int,
    company_id: int,
    visual_steps: dict
) -> List[WorkflowTrigger]:
    """
    Synchronize workflow triggers based on visual workflow nodes.

    This function:
    1. Extracts trigger nodes from the visual workflow
    2. Removes triggers that are no longer in the visual workflow
    3. Creates or updates triggers based on current visual nodes

    Args:
        db: Database session
        workflow_id: ID of the workflow
        company_id: ID of the company
        visual_steps: Visual workflow data (dict or JSON string)

    Returns:
        List of WorkflowTrigger objects that are now active
    """
    # Parse visual_steps if it's a JSON string
    if isinstance(visual_steps, str):
        try:
            visual_steps = json.loads(visual_steps)
        except (json.JSONDecodeError, TypeError):
            visual_steps = {}

    # Extract trigger nodes from visual workflow
    trigger_nodes = extract_trigger_nodes_from_visual_steps(visual_steps)

    # Get existing triggers for this workflow
    existing_triggers = db.query(WorkflowTrigger).filter(
        WorkflowTrigger.workflow_id == workflow_id,
        WorkflowTrigger.company_id == company_id
    ).all()

    # Create a mapping of existing triggers by node_id (stored in config)
    existing_by_node_id = {
        t.config.get('node_id') if t.config else None: t
        for t in existing_triggers
    }

    # Track which trigger node IDs we've seen
    processed_node_ids = set()
    result_triggers = []

    # Process each trigger node from visual workflow
    for node in trigger_nodes:
        node_id = node.get('id')
        node_type = node.get('type')
        node_data = node.get('data', {})

        if not node_id or not node_type:
            continue

        processed_node_ids.add(node_id)
        channel = map_trigger_type_to_channel(node_type)

        if not channel:
            continue

        # Check if this trigger already exists
        existing_trigger = existing_by_node_id.get(node_id)

        if existing_trigger:
            # Update existing trigger
            existing_trigger.channel = channel
            existing_trigger.label = node_data.get('label')
            existing_trigger.fallback_agent_id = node_data.get('agent_id')
            existing_trigger.auto_respond = node_data.get('auto_respond', True)
            existing_trigger.is_active = True
            existing_trigger.config = {
                'node_id': node_id,
                'position': node.get('position', {}),
            }
            result_triggers.append(existing_trigger)
        else:
            # Create new trigger
            new_trigger = WorkflowTrigger(
                workflow_id=workflow_id,
                company_id=company_id,
                channel=channel,
                label=node_data.get('label'),
                fallback_agent_id=node_data.get('agent_id'),
                auto_respond=node_data.get('auto_respond', True),
                is_active=True,
                config={
                    'node_id': node_id,
                    'position': node.get('position', {}),
                }
            )
            db.add(new_trigger)
            result_triggers.append(new_trigger)

    # Remove triggers that are no longer in the visual workflow
    for trigger in existing_triggers:
        trigger_node_id = trigger.config.get('node_id') if trigger.config else None
        if trigger_node_id and trigger_node_id not in processed_node_ids:
            db.delete(trigger)

    db.commit()

    # Refresh all triggers
    for trigger in result_triggers:
        db.refresh(trigger)

    return result_triggers


def get_triggers_for_workflow(
    db: Session,
    workflow_id: int,
    company_id: int
) -> List[WorkflowTrigger]:
    """
    Get all active triggers for a workflow.

    Args:
        db: Database session
        workflow_id: ID of the workflow
        company_id: ID of the company

    Returns:
        List of active WorkflowTrigger objects
    """
    return db.query(WorkflowTrigger).filter(
        WorkflowTrigger.workflow_id == workflow_id,
        WorkflowTrigger.company_id == company_id,
        WorkflowTrigger.is_active == True
    ).all()


def get_triggers_by_channel(
    db: Session,
    channel: TriggerChannel,
    company_id: int
) -> List[WorkflowTrigger]:
    """
    Get all active triggers for a specific channel.

    Args:
        db: Database session
        channel: The channel type to filter by
        company_id: ID of the company

    Returns:
        List of active WorkflowTrigger objects for the channel
    """
    return db.query(WorkflowTrigger).join(
        Workflow, WorkflowTrigger.workflow_id == Workflow.id
    ).filter(
        WorkflowTrigger.channel == channel,
        WorkflowTrigger.company_id == company_id,
        WorkflowTrigger.is_active == True,
        Workflow.is_active == True  # Only triggers for active workflows
    ).all()


def delete_triggers_for_workflow(
    db: Session,
    workflow_id: int,
    company_id: int
) -> bool:
    """
    Delete all triggers for a workflow.

    Args:
        db: Database session
        workflow_id: ID of the workflow
        company_id: ID of the company

    Returns:
        True if triggers were deleted, False otherwise
    """
    triggers = db.query(WorkflowTrigger).filter(
        WorkflowTrigger.workflow_id == workflow_id,
        WorkflowTrigger.company_id == company_id
    ).all()

    for trigger in triggers:
        db.delete(trigger)

    db.commit()
    return len(triggers) > 0


def find_workflow_for_channel_message(
    db: Session,
    channel: TriggerChannel,
    company_id: int,
    message: str,
    session_data: dict = None
) -> Optional[Workflow]:
    """
    Find the most appropriate workflow for a message received on a specific channel.

    This function:
    1. Gets all active triggers for the channel
    2. For each workflow with a trigger, checks if the message matches any intent
    3. Returns the workflow with the highest confidence match

    Args:
        db: Database session
        channel: The channel type (websocket, whatsapp, etc.)
        company_id: ID of the company
        message: The incoming message text
        session_data: Optional session context data

    Returns:
        Workflow object if a match is found, None otherwise
    """
    from app.services.workflow_intent_service import WorkflowIntentService

    # Get all active triggers for this channel
    triggers = get_triggers_by_channel(db, channel, company_id)

    if not triggers:
        return None

    # For now, we'll use intent detection to find the best workflow
    # Later this could be enhanced with priority, filters, etc.
    intent_service = WorkflowIntentService(db)
    best_match = None
    best_confidence = 0.0

    for trigger in triggers:
        workflow = db.query(Workflow).filter(
            Workflow.id == trigger.workflow_id,
            Workflow.is_active == True
        ).first()

        if not workflow or not workflow.intent_config:
            continue

        intent_config = workflow.intent_config if isinstance(workflow.intent_config, dict) else {}
        if not intent_config.get('enabled', False):
            continue

        # Check if message matches any intent for this workflow
        result = intent_service.detect_intent(
            workflow_id=workflow.id,
            company_id=company_id,
            message=message
        )

        if result['matched'] and result['confidence'] > best_confidence:
            best_confidence = result['confidence']
            best_match = workflow

    return best_match
