from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List, Dict, Any
from datetime import date, timedelta

from app.core.dependencies import get_db
from app.core.auth import get_current_user
from app.models.user import User
from app.models.chat_message import ChatMessage
from app.models.conversation_session import ConversationSession
from app.models.agent import Agent

router = APIRouter()

@router.get("/metrics", response_model=Dict[str, Any])
def get_overall_metrics(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    start_date: date = Query(date.today() - timedelta(days=30)),
    end_date: date = Query(date.today())
):
    company_id = current_user.company_id

    # Total Conversations
    total_conversations = db.query(ConversationSession).filter(
        ConversationSession.company_id == company_id,
        ConversationSession.created_at >= start_date,
        ConversationSession.created_at <= end_date
    ).count()

    # Total Messages
    total_messages = db.query(ChatMessage).filter(
        ChatMessage.company_id == company_id,
        ChatMessage.timestamp >= start_date,
        ChatMessage.timestamp <= end_date
    ).count()

    # Active Agents
    active_agents = db.query(Agent).filter(
        Agent.company_id == company_id,
        Agent.is_active == True
    ).count()

    # Placeholder for Avg Response Time and Customer Satisfaction
    # These would require more complex logic and data points (e.g., message timestamps, satisfaction ratings)
    avg_response_time = "N/A" # Implement logic to calculate this
    customer_satisfaction = "N/A" # Implement logic to calculate this

    return {
        "total_conversations": total_conversations,
        "total_messages": total_messages,
        "active_agents": active_agents,
        "avg_response_time": avg_response_time,
        "customer_satisfaction": customer_satisfaction
    }

@router.get("/agent-performance", response_model=List[Dict[str, Any]])
def get_agent_performance(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    start_date: date = Query(date.today() - timedelta(days=30)),
    end_date: date = Query(date.today())
):
    company_id = current_user.company_id

    # This is a simplified example. A real implementation would involve:
    # 1. Joining ChatMessage and Agent tables.
    # 2. Grouping by agent_id and agent name.
    # 3. Counting conversations/messages per agent.
    # 4. Calculating average response times (requires message timestamps).
    # 5. Aggregating satisfaction scores (requires a satisfaction rating mechanism).

    agents_data = db.query(Agent).filter(Agent.company_id == company_id).all()
    
    performance_data = []
    for agent in agents_data:
        conversations_count = db.query(ConversationSession).filter(
            ConversationSession.company_id == company_id,
            ConversationSession.agent_id == agent.id,
            ConversationSession.created_at >= start_date,
            ConversationSession.created_at <= end_date
        ).count()

        performance_data.append({
            "agent_id": agent.id,
            "agent_name": agent.name,
            "conversations": conversations_count,
            "avg_response": "N/A", # Placeholder
            "satisfaction": "N/A" # Placeholder
        })
    return performance_data

@router.get("/customer-satisfaction", response_model=List[Dict[str, Any]])
def get_customer_satisfaction(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    start_date: date = Query(date.today() - timedelta(days=30)),
    end_date: date = Query(date.today())
):
    # Placeholder data for customer satisfaction. 
    # In a real scenario, this would come from user feedback/ratings.
    return [
        {"rating": 5, "percentage": 60},
        {"rating": 4, "percentage": 25},
        {"rating": 3, "percentage": 10},
        {"rating": 2, "percentage": 3},
        {"rating": 1, "percentage": 2}
    ]

@router.get("/top-issues", response_model=List[Dict[str, Any]])
def get_top_issues(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    start_date: date = Query(date.today() - timedelta(days=30)),
    end_date: date = Query(date.today())
):
    # Placeholder data for top issues. 
    # In a real scenario, this would come from categorizing chat messages/conversations.
    return [
        {"issue": "Account Access", "count": 45},
        {"issue": "Billing Questions", "count": 32},
        {"issue": "Technical Support", "count": 28},
        {"issue": "Product Information", "count": 21},
        {"issue": "Feature Requests", "count": 15}
    ]
