"""
Agent selection service for topic-based agent matching.
Handles finding the best agent for a given topic or specialization.
Used by agent-to-agent handoff and consultation features.
"""
from sqlalchemy.orm import Session
from sqlalchemy import and_
from app.models.agent import Agent
from typing import Optional, List
import logging

logger = logging.getLogger(__name__)


def find_agent_by_topic(
    db: Session,
    topic: str,
    company_id: int,
    exclude_agent_id: Optional[int] = None
) -> Optional[Agent]:
    """
    Finds the best matching agent for a given topic.

    Args:
        db: Database session
        topic: The topic/area to match (e.g., "billing", "technical_support")
        company_id: Company ID for filtering
        exclude_agent_id: Agent ID to exclude (typically the current agent)

    Returns:
        Best matching Agent or None if no match found
    """
    # Query all active agents in the company
    query = db.query(Agent).filter(
        and_(
            Agent.company_id == company_id,
            Agent.is_active == True,
            Agent.status == "active"
        )
    )

    if exclude_agent_id:
        query = query.filter(Agent.id != exclude_agent_id)

    agents = query.all()

    best_match = None
    best_score = 0
    topic_lower = topic.lower().strip()

    for agent in agents:
        # Check handoff_config - skip agents that don't accept handoffs
        handoff_config = agent.handoff_config or {}
        if not handoff_config.get("accept_handoffs", True):
            continue

        # Check specialization_topics
        specializations = agent.specialization_topics or []
        if not specializations:
            continue

        for spec in specializations:
            spec_topic = spec.get("topic", "").lower().strip()
            spec_description = spec.get("description", "").lower()

            # Exact match on topic name - highest priority
            if topic_lower == spec_topic:
                logger.info(f"[AGENT SELECTION] Exact match for topic '{topic}': {agent.name} (id: {agent.id})")
                return agent  # Perfect match - return immediately

            # Scoring for partial matches
            score = 0

            # Topic contains or is contained
            if topic_lower in spec_topic or spec_topic in topic_lower:
                score += 10

            # Topic mentioned in description
            if topic_lower in spec_description:
                score += 5

            # Keyword matching - split topic into words and check
            topic_words = set(topic_lower.replace("_", " ").replace("-", " ").split())
            spec_words = set(spec_topic.replace("_", " ").replace("-", " ").split())
            desc_words = set(spec_description.split())

            # Common words in topic name
            common_topic_words = topic_words & spec_words
            score += len(common_topic_words) * 4

            # Common words in description
            common_desc_words = topic_words & desc_words
            score += len(common_desc_words) * 2

            if score > best_score:
                best_score = score
                best_match = agent

    if best_match:
        logger.info(f"[AGENT SELECTION] Best match for topic '{topic}': {best_match.name} (id: {best_match.id}, score: {best_score})")
    else:
        logger.warning(f"[AGENT SELECTION] No agent found for topic '{topic}' in company {company_id}")

    return best_match


def get_agent_by_id_if_available(
    db: Session,
    agent_id: int,
    company_id: int
) -> Optional[Agent]:
    """
    Gets a specific agent if it exists, is active, and accepts handoffs.

    Args:
        db: Database session
        agent_id: The agent ID to lookup
        company_id: Company ID for filtering

    Returns:
        Agent if available for handoff, None otherwise
    """
    agent = db.query(Agent).filter(
        and_(
            Agent.id == agent_id,
            Agent.company_id == company_id,
            Agent.is_active == True,
            Agent.status == "active"
        )
    ).first()

    if not agent:
        logger.warning(f"[AGENT SELECTION] Agent {agent_id} not found or not active")
        return None

    # Check if agent accepts handoffs
    handoff_config = agent.handoff_config or {}
    if not handoff_config.get("accept_handoffs", True):
        logger.warning(f"[AGENT SELECTION] Agent {agent_id} ({agent.name}) does not accept handoffs")
        return None

    return agent


def list_available_agents_for_handoff(
    db: Session,
    company_id: int,
    exclude_agent_id: Optional[int] = None
) -> List[dict]:
    """
    Lists all agents available for handoff with their specializations.
    Useful for UI to show available transfer options.

    Args:
        db: Database session
        company_id: Company ID for filtering
        exclude_agent_id: Agent ID to exclude (typically the current agent)

    Returns:
        List of agent info dictionaries with id, name, specializations
    """
    query = db.query(Agent).filter(
        and_(
            Agent.company_id == company_id,
            Agent.is_active == True,
            Agent.status == "active"
        )
    )

    if exclude_agent_id:
        query = query.filter(Agent.id != exclude_agent_id)

    agents = query.all()
    result = []

    for agent in agents:
        handoff_config = agent.handoff_config or {}

        # Skip agents that don't accept handoffs
        if not handoff_config.get("accept_handoffs", True):
            continue

        # Skip agents without specializations
        specializations = agent.specialization_topics or []
        if not specializations:
            continue

        result.append({
            "id": agent.id,
            "name": agent.name,
            "specialization_topics": specializations,
            "history_mode": handoff_config.get("history_mode", "summary"),
            "welcome_message_on_handoff": handoff_config.get("welcome_message_on_handoff")
        })

    return result


def get_agent_history_mode(agent: Agent) -> str:
    """
    Gets the history mode preference for an agent.

    Args:
        agent: The Agent object

    Returns:
        History mode: "full", "summary", or "none"
    """
    handoff_config = agent.handoff_config or {}
    return handoff_config.get("history_mode", "summary")


def get_agent_welcome_message(agent: Agent, topic: str) -> str:
    """
    Gets the welcome message for an agent receiving a handoff.

    Args:
        agent: The Agent object
        topic: The topic that triggered the handoff

    Returns:
        Welcome message string
    """
    handoff_config = agent.handoff_config or {}
    custom_message = handoff_config.get("welcome_message_on_handoff")

    if custom_message:
        return custom_message

    # Generate default welcome message
    return f"Hello! I'm {agent.name}, and I specialize in {topic}. I've been brought in to help with your request. How can I assist you?"
