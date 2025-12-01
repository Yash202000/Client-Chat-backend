"""
Lead Qualification Service
Implements hybrid lead scoring: AI intent + engagement + behavioral + workflow + manual
"""
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from app.models.lead import Lead, LeadStage, QualificationStatus
from app.models.lead_score import LeadScore, ScoreType
from app.models.campaign_contact import CampaignContact
from app.models.campaign_activity import CampaignActivity, ActivityType
from app.models.intent import IntentMatch
from app.schemas.lead_score import LeadScoreCreate


def calculate_ai_intent_score(
    db: Session,
    lead_id: int,
    conversation_session_id: Optional[str] = None
) -> Optional[LeadScore]:
    """
    Calculate lead score based on AI-detected intent from conversations
    """
    from app.models.conversation_session import ConversationSession

    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        return None

    # Get intent matches for this lead's contact from conversations
    # Join IntentMatch with ConversationSession to filter by contact_id
    intent_matches = db.query(IntentMatch).join(
        ConversationSession,
        IntentMatch.conversation_id == ConversationSession.conversation_id
    ).filter(
        ConversationSession.contact_id == lead.contact_id
    ).order_by(IntentMatch.matched_at.desc()).limit(10).all()

    if not intent_matches:
        return None

    # Calculate score based on intent confidence and types
    score_value = 0
    intent_data = []

    purchase_keywords = ['buy', 'purchase', 'pricing', 'price', 'cost', 'demo', 'trial', 'enterprise', 'plan']
    urgency_keywords = ['urgent', 'asap', 'immediately', 'today', 'now', 'quickly']

    for match in intent_matches:
        intent_score = int(match.confidence_score * 100)

        # Boost score for purchase-related intents
        intent_name_lower = (match.intent.name if hasattr(match, 'intent') else '').lower()
        if any(keyword in intent_name_lower for keyword in purchase_keywords):
            intent_score = int(intent_score * 1.5)

        # Boost for urgency
        if match.extracted_entities:
            entities_str = str(match.extracted_entities).lower()
            if any(keyword in entities_str for keyword in urgency_keywords):
                intent_score = int(intent_score * 1.2)

        score_value += intent_score

        intent_data.append({
            'intent_id': match.intent_id,
            'intent_name': intent_name_lower,
            'confidence': match.confidence_score,
            'timestamp': match.matched_at.isoformat() if match.matched_at else None,
            'entities': match.extracted_entities
        })

    # Average and cap at 100
    avg_score = min(100, int(score_value / len(intent_matches)))

    # Create score record
    score = LeadScore(
        lead_id=lead_id,
        company_id=lead.company_id,
        score_type=ScoreType.AI_INTENT,
        score_value=avg_score,
        confidence=sum(m.confidence_score for m in intent_matches) / len(intent_matches),
        intent_matches=intent_data,
        score_reason=f"Analyzed {len(intent_matches)} conversation intents with average confidence {avg_score}%",
        score_factors={'intent_count': len(intent_matches), 'intents': intent_data},
        conversation_session_id=conversation_session_id
    )

    db.add(score)
    db.commit()
    db.refresh(score)

    return score


def calculate_engagement_score(
    db: Session,
    lead_id: int,
    lookback_days: int = 30
) -> Optional[LeadScore]:
    """
    Calculate lead score based on campaign engagement (opens, clicks, replies)
    """
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        return None

    since_date = datetime.utcnow() - timedelta(days=lookback_days)

    # Get campaign enrollments for this lead
    enrollments = db.query(CampaignContact).filter(
        CampaignContact.lead_id == lead_id,
        CampaignContact.enrolled_at >= since_date
    ).all()

    if not enrollments:
        return None

    # Calculate engagement metrics
    total_opens = sum(e.opens for e in enrollments)
    total_clicks = sum(e.clicks for e in enrollments)
    total_replies = sum(e.replies for e in enrollments)
    total_calls_completed = sum(e.calls_completed for e in enrollments)

    # Scoring formula (weighted)
    score_value = 0
    score_value += min(30, total_opens * 3)  # Max 30 points from opens
    score_value += min(30, total_clicks * 5)  # Max 30 points from clicks
    score_value += min(25, total_replies * 8)  # Max 25 points from replies
    score_value += min(15, total_calls_completed * 10)  # Max 15 points from calls

    score_value = min(100, int(score_value))

    # Create score record
    score = LeadScore(
        lead_id=lead_id,
        company_id=lead.company_id,
        score_type=ScoreType.ENGAGEMENT,
        score_value=score_value,
        score_reason=f"Based on {lookback_days} days of campaign engagement",
        score_factors={
            'opens': total_opens,
            'clicks': total_clicks,
            'replies': total_replies,
            'calls_completed': total_calls_completed,
            'lookback_days': lookback_days
        }
    )

    db.add(score)
    db.commit()
    db.refresh(score)

    return score


def calculate_demographic_score(
    db: Session,
    lead_id: int,
    scoring_rules: Optional[Dict[str, Any]] = None
) -> Optional[LeadScore]:
    """
    Calculate score based on demographic fit (company size, industry, role, etc.)
    Uses lead.qualification_data or lead.custom_fields
    """
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        return None

    # Default scoring rules
    if not scoring_rules:
        scoring_rules = {
            'company_size': {
                '1-10': 20,
                '11-50': 40,
                '51-200': 60,
                '201-500': 80,
                '500+': 100
            },
            'industry': {
                'technology': 90,
                'finance': 85,
                'healthcare': 80,
                'retail': 70,
                'education': 65
            },
            'role': {
                'ceo': 100,
                'cto': 95,
                'vp': 90,
                'director': 80,
                'manager': 70,
                'other': 50
            }
        }

    # Get demographic data from qualification_data or custom_fields
    demographic_data = lead.qualification_data or lead.custom_fields or {}

    score_value = 0
    score_details = {}

    for field, rules in scoring_rules.items():
        if field in demographic_data:
            value = str(demographic_data[field]).lower()
            for key, points in rules.items():
                if key.lower() in value:
                    score_value += points
                    score_details[field] = {'value': value, 'points': points}
                    break

    # Average the scores
    if score_details:
        score_value = min(100, int(score_value / len(score_details)))
    else:
        score_value = 50  # Neutral score if no data

    # Create score record
    score = LeadScore(
        lead_id=lead_id,
        company_id=lead.company_id,
        score_type=ScoreType.DEMOGRAPHIC,
        score_value=score_value,
        score_reason=f"Demographic fit based on {len(score_details)} factors",
        score_factors={'demographics': score_details}
    )

    db.add(score)
    db.commit()
    db.refresh(score)

    return score


def calculate_workflow_score(
    db: Session,
    lead_id: int
) -> Optional[LeadScore]:
    """
    Calculate score based on workflow completion and qualification questions
    """
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead or not lead.qualification_data:
        return None

    qualification_data = lead.qualification_data

    # Count completed qualification steps
    total_questions = len(qualification_data)
    answered_questions = sum(1 for v in qualification_data.values() if v is not None and v != '')

    # Base score on completion percentage
    completion_pct = (answered_questions / total_questions) * 100 if total_questions > 0 else 0

    # Boost score for positive answers to key questions
    positive_boost = 0
    if qualification_data.get('budget_confirmed'):
        positive_boost += 15
    if qualification_data.get('timeline_defined'):
        positive_boost += 15
    if qualification_data.get('decision_maker_involved'):
        positive_boost += 20

    score_value = min(100, int(completion_pct + positive_boost))

    # Create score record
    score = LeadScore(
        lead_id=lead_id,
        company_id=lead.company_id,
        score_type=ScoreType.WORKFLOW,
        score_value=score_value,
        score_reason=f"Workflow qualification: {answered_questions}/{total_questions} questions answered",
        score_factors={
            'total_questions': total_questions,
            'answered_questions': answered_questions,
            'completion_percentage': completion_pct,
            'qualification_data': qualification_data
        }
    )

    db.add(score)
    db.commit()
    db.refresh(score)

    return score


def create_manual_score(
    db: Session,
    lead_id: int,
    score_value: int,
    user_id: int,
    reason: Optional[str] = None
) -> Optional[LeadScore]:
    """
    Create a manual score set by a sales rep
    """
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        return None

    score = LeadScore(
        lead_id=lead_id,
        company_id=lead.company_id,
        score_type=ScoreType.MANUAL,
        score_value=min(100, max(0, score_value)),
        scored_by_user_id=user_id,
        score_reason=reason or "Manually set by sales rep"
    )

    db.add(score)
    db.commit()
    db.refresh(score)

    return score


def calculate_combined_score(
    db: Session,
    lead_id: int,
    weights: Optional[Dict[str, float]] = None
) -> int:
    """
    Calculate weighted combined score from all score types
    """
    if not weights:
        weights = {
            ScoreType.AI_INTENT: 0.25,
            ScoreType.ENGAGEMENT: 0.25,
            ScoreType.DEMOGRAPHIC: 0.15,
            ScoreType.WORKFLOW: 0.20,
            ScoreType.MANUAL: 0.15
        }

    # Get latest scores of each type
    scores = db.query(LeadScore).filter(
        LeadScore.lead_id == lead_id
    ).order_by(LeadScore.scored_at.desc()).all()

    # Group by score type, keep latest
    latest_scores = {}
    for score in scores:
        if score.score_type not in latest_scores:
            latest_scores[score.score_type] = score

    # Calculate weighted average
    weighted_sum = 0
    total_weight = 0

    for score_type, weight in weights.items():
        if score_type in latest_scores:
            weighted_sum += latest_scores[score_type].score_value * weight
            total_weight += weight

    # Normalize to 0-100
    if total_weight > 0:
        combined_score = int(weighted_sum / total_weight)
    else:
        combined_score = 0

    # Create combined score record
    combined = LeadScore(
        lead_id=lead_id,
        company_id=latest_scores[next(iter(latest_scores))].company_id if latest_scores else None,
        score_type=ScoreType.COMBINED,
        score_value=combined_score,
        score_reason=f"Weighted combination of {len(latest_scores)} score types",
        score_factors={
            'weights': {str(k): v for k, v in weights.items()},
            'scores': {str(k): v.score_value for k, v in latest_scores.items()}
        }
    )

    db.add(combined)
    db.commit()

    return combined_score


def auto_qualify_lead(
    db: Session,
    lead_id: int,
    min_score_threshold: int = 70
) -> Lead:
    """
    Automatically qualify/disqualify lead based on combined score
    """
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        return None

    # Calculate all scores
    calculate_ai_intent_score(db, lead_id)
    calculate_engagement_score(db, lead_id)
    calculate_workflow_score(db, lead_id)

    # Get combined score
    combined_score = calculate_combined_score(db, lead_id)

    # Update lead score
    lead.score = combined_score
    lead.last_scored_at = datetime.utcnow()

    # Auto-qualify based on threshold
    if combined_score >= min_score_threshold:
        if lead.qualification_status == QualificationStatus.UNQUALIFIED:
            lead.qualification_status = QualificationStatus.QUALIFIED

        # Auto-promote to MQL if still in LEAD stage
        if lead.stage == LeadStage.LEAD and combined_score >= 75:
            lead.stage = LeadStage.MQL
            lead.stage_changed_at = datetime.utcnow()
    elif combined_score < 40:
        lead.qualification_status = QualificationStatus.DISQUALIFIED

    db.commit()
    db.refresh(lead)

    return lead


def get_lead_scoring_breakdown(db: Session, lead_id: int) -> Dict[str, Any]:
    """
    Get detailed breakdown of all scores for a lead
    """
    scores = db.query(LeadScore).filter(
        LeadScore.lead_id == lead_id
    ).order_by(LeadScore.scored_at.desc()).all()

    breakdown = {
        'lead_id': lead_id,
        'scores_by_type': {},
        'latest_combined_score': None,
        'total_scores': len(scores)
    }

    for score in scores:
        score_type_str = score.score_type.value
        if score_type_str not in breakdown['scores_by_type']:
            breakdown['scores_by_type'][score_type_str] = {
                'latest_score': score.score_value,
                'latest_scored_at': score.scored_at.isoformat(),
                'reason': score.score_reason,
                'factors': score.score_factors,
                'confidence': score.confidence,
                'history_count': 1
            }
        else:
            breakdown['scores_by_type'][score_type_str]['history_count'] += 1

        if score.score_type == ScoreType.COMBINED:
            breakdown['latest_combined_score'] = score.score_value

    return breakdown
