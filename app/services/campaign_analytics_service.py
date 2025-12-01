"""
Campaign Analytics Service
Provides comprehensive analytics and reporting for campaigns and leads
"""
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_, case
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from decimal import Decimal
from app.models.campaign import Campaign, CampaignStatus, CampaignType
from app.models.campaign_contact import CampaignContact, EnrollmentStatus
from app.models.campaign_message import CampaignMessage
from app.models.campaign_activity import CampaignActivity, ActivityType
from app.models.lead import Lead, LeadStage
from app.models.contact import Contact


def get_campaign_performance_metrics(db: Session, campaign_id: int, company_id: int) -> Dict[str, Any]:
    """
    Get comprehensive performance metrics for a campaign
    """
    campaign = db.query(Campaign).filter(
        Campaign.id == campaign_id,
        Campaign.company_id == company_id
    ).first()

    if not campaign:
        return {}

    # Enrollment metrics
    total_enrolled = db.query(func.count(CampaignContact.id)).filter(
        CampaignContact.campaign_id == campaign_id
    ).scalar() or 0

    active_enrollments = db.query(func.count(CampaignContact.id)).filter(
        CampaignContact.campaign_id == campaign_id,
        CampaignContact.status == EnrollmentStatus.ACTIVE
    ).scalar() or 0

    completed_enrollments = db.query(func.count(CampaignContact.id)).filter(
        CampaignContact.campaign_id == campaign_id,
        CampaignContact.status == EnrollmentStatus.COMPLETED
    ).scalar() or 0

    opted_out = db.query(func.count(CampaignContact.id)).filter(
        CampaignContact.campaign_id == campaign_id,
        CampaignContact.status == EnrollmentStatus.OPTED_OUT
    ).scalar() or 0

    # Activity metrics by type
    activities = db.query(
        CampaignActivity.activity_type,
        func.count(CampaignActivity.id).label('count')
    ).filter(
        CampaignActivity.campaign_id == campaign_id
    ).group_by(CampaignActivity.activity_type).all()

    activity_counts = {activity.activity_type.value: activity.count for activity in activities}

    # Email metrics
    emails_sent = activity_counts.get(ActivityType.EMAIL_SENT.value, 0)
    emails_delivered = activity_counts.get(ActivityType.EMAIL_DELIVERED.value, 0)
    emails_opened = activity_counts.get(ActivityType.EMAIL_OPENED.value, 0)
    emails_clicked = activity_counts.get(ActivityType.EMAIL_CLICKED.value, 0)
    emails_replied = activity_counts.get(ActivityType.EMAIL_REPLIED.value, 0)

    # Calculate rates
    open_rate = (emails_opened / emails_delivered * 100) if emails_delivered > 0 else 0
    click_rate = (emails_clicked / emails_delivered * 100) if emails_delivered > 0 else 0
    reply_rate = (emails_replied / emails_delivered * 100) if emails_delivered > 0 else 0
    click_to_open_rate = (emails_clicked / emails_opened * 100) if emails_opened > 0 else 0

    # Voice campaign metrics
    calls_initiated = activity_counts.get(ActivityType.CALL_INITIATED.value, 0)
    calls_answered = activity_counts.get(ActivityType.CALL_ANSWERED.value, 0)
    calls_completed = activity_counts.get(ActivityType.CALL_COMPLETED.value, 0)
    voicemails = activity_counts.get(ActivityType.VOICEMAIL_LEFT.value, 0)

    answer_rate = (calls_answered / calls_initiated * 100) if calls_initiated > 0 else 0

    # Total call duration
    total_duration = db.query(func.sum(CampaignContact.total_call_duration)).filter(
        CampaignContact.campaign_id == campaign_id
    ).scalar() or 0

    avg_call_duration = (total_duration / calls_completed) if calls_completed > 0 else 0

    # Conversion metrics
    conversions = db.query(func.sum(CampaignContact.conversions)).filter(
        CampaignContact.campaign_id == campaign_id
    ).scalar() or 0

    conversion_rate = (conversions / total_enrolled * 100) if total_enrolled > 0 else 0

    # Revenue metrics
    total_revenue = db.query(func.sum(CampaignActivity.revenue_amount)).filter(
        CampaignActivity.campaign_id == campaign_id
    ).scalar() or Decimal(0)

    # ROI calculation
    budget = campaign.budget or Decimal(0)
    actual_cost = campaign.actual_cost or Decimal(0)
    roi = ((total_revenue - actual_cost) / actual_cost * 100) if actual_cost > 0 else 0

    return {
        'campaign_id': campaign_id,
        'campaign_name': campaign.name,
        'campaign_type': campaign.campaign_type.value,
        'status': campaign.status.value,

        # Enrollment metrics
        'total_enrolled': total_enrolled,
        'active': active_enrollments,
        'completed': completed_enrollments,
        'opted_out': opted_out,
        'completion_rate': (completed_enrollments / total_enrolled * 100) if total_enrolled > 0 else 0,
        'opt_out_rate': (opted_out / total_enrolled * 100) if total_enrolled > 0 else 0,

        # Email metrics
        'emails_sent': emails_sent,
        'emails_delivered': emails_delivered,
        'emails_opened': emails_opened,
        'emails_clicked': emails_clicked,
        'emails_replied': emails_replied,
        'open_rate': round(open_rate, 2),
        'click_rate': round(click_rate, 2),
        'reply_rate': round(reply_rate, 2),
        'click_to_open_rate': round(click_to_open_rate, 2),

        # Voice metrics
        'calls_initiated': calls_initiated,
        'calls_answered': calls_answered,
        'calls_completed': calls_completed,
        'voicemails_left': voicemails,
        'answer_rate': round(answer_rate, 2),
        'total_call_duration': int(total_duration),
        'avg_call_duration': round(avg_call_duration, 2),

        # Conversion metrics
        'conversions': conversions,
        'conversion_rate': round(conversion_rate, 2),

        # Revenue metrics
        'total_revenue': float(total_revenue),
        'budget': float(budget),
        'actual_cost': float(actual_cost),
        'roi': round(float(roi), 2),

        # Timeline
        'start_date': campaign.start_date.isoformat() if campaign.start_date else None,
        'end_date': campaign.end_date.isoformat() if campaign.end_date else None,
        'last_run_at': campaign.last_run_at.isoformat() if campaign.last_run_at else None,
    }


def get_campaign_funnel(db: Session, campaign_id: int, company_id: int) -> List[Dict[str, Any]]:
    """
    Get campaign funnel showing drop-off at each stage
    """
    campaign = db.query(Campaign).filter(
        Campaign.id == campaign_id,
        Campaign.company_id == company_id
    ).first()

    if not campaign:
        return []

    # Define funnel stages based on campaign type
    if campaign.campaign_type == CampaignType.EMAIL:
        stages = [
            {'name': 'Enrolled', 'count_query': lambda: db.query(func.count(CampaignContact.id)).filter(CampaignContact.campaign_id == campaign_id)},
            {'name': 'Delivered', 'activity_type': ActivityType.EMAIL_DELIVERED},
            {'name': 'Opened', 'activity_type': ActivityType.EMAIL_OPENED},
            {'name': 'Clicked', 'activity_type': ActivityType.EMAIL_CLICKED},
            {'name': 'Replied', 'activity_type': ActivityType.EMAIL_REPLIED},
            {'name': 'Converted', 'count_query': lambda: db.query(func.sum(CampaignContact.conversions)).filter(CampaignContact.campaign_id == campaign_id)},
        ]
    elif campaign.campaign_type == CampaignType.VOICE:
        stages = [
            {'name': 'Enrolled', 'count_query': lambda: db.query(func.count(CampaignContact.id)).filter(CampaignContact.campaign_id == campaign_id)},
            {'name': 'Called', 'activity_type': ActivityType.CALL_INITIATED},
            {'name': 'Answered', 'activity_type': ActivityType.CALL_ANSWERED},
            {'name': 'Completed', 'activity_type': ActivityType.CALL_COMPLETED},
            {'name': 'Converted', 'count_query': lambda: db.query(func.sum(CampaignContact.conversions)).filter(CampaignContact.campaign_id == campaign_id)},
        ]
    else:
        stages = [
            {'name': 'Enrolled', 'count_query': lambda: db.query(func.count(CampaignContact.id)).filter(CampaignContact.campaign_id == campaign_id)},
            {'name': 'Reached', 'count_query': lambda: db.query(func.count(CampaignContact.id)).filter(CampaignContact.campaign_id == campaign_id, CampaignContact.current_step > 0)},
            {'name': 'Engaged', 'count_query': lambda: db.query(func.count(CampaignContact.id)).filter(CampaignContact.campaign_id == campaign_id, or_(CampaignContact.opens > 0, CampaignContact.clicks > 0, CampaignContact.replies > 0))},
            {'name': 'Converted', 'count_query': lambda: db.query(func.sum(CampaignContact.conversions)).filter(CampaignContact.campaign_id == campaign_id)},
        ]

    funnel = []
    previous_count = None

    for i, stage in enumerate(stages):
        if 'count_query' in stage:
            count = stage['count_query']().scalar() or 0
        else:
            count = db.query(func.count(func.distinct(CampaignActivity.contact_id))).filter(
                CampaignActivity.campaign_id == campaign_id,
                CampaignActivity.activity_type == stage['activity_type']
            ).scalar() or 0

        if previous_count is not None:
            drop_off = previous_count - count
            drop_off_rate = (drop_off / previous_count * 100) if previous_count > 0 else 0
        else:
            drop_off = 0
            drop_off_rate = 0

        funnel.append({
            'stage': stage['name'],
            'count': count,
            'drop_off': drop_off,
            'drop_off_rate': round(drop_off_rate, 2)
        })

        previous_count = count

    return funnel


def get_message_performance(db: Session, campaign_id: int, company_id: int) -> List[Dict[str, Any]]:
    """
    Get performance metrics for each message in the campaign sequence
    """
    campaign = db.query(Campaign).filter(
        Campaign.id == campaign_id,
        Campaign.company_id == company_id
    ).first()

    if not campaign:
        return []

    messages = db.query(CampaignMessage).filter(
        CampaignMessage.campaign_id == campaign_id
    ).order_by(CampaignMessage.sequence_order).all()

    performance = []

    for message in messages:
        # Count activities for this message
        sent = db.query(func.count(CampaignActivity.id)).filter(
            CampaignActivity.message_id == message.id,
            CampaignActivity.activity_type.in_([ActivityType.EMAIL_SENT, ActivityType.SMS_SENT, ActivityType.WHATSAPP_SENT, ActivityType.CALL_INITIATED])
        ).scalar() or 0

        opened = db.query(func.count(CampaignActivity.id)).filter(
            CampaignActivity.message_id == message.id,
            CampaignActivity.activity_type.in_([ActivityType.EMAIL_OPENED, ActivityType.WHATSAPP_READ])
        ).scalar() or 0

        clicked = db.query(func.count(CampaignActivity.id)).filter(
            CampaignActivity.message_id == message.id,
            CampaignActivity.activity_type == ActivityType.EMAIL_CLICKED
        ).scalar() or 0

        replied = db.query(func.count(CampaignActivity.id)).filter(
            CampaignActivity.message_id == message.id,
            CampaignActivity.activity_type.in_([ActivityType.EMAIL_REPLIED, ActivityType.SMS_REPLIED, ActivityType.WHATSAPP_REPLIED, ActivityType.CONVERSATION_REPLIED])
        ).scalar() or 0

        performance.append({
            'message_id': message.id,
            'sequence_order': message.sequence_order,
            'name': message.name or f"Message {message.sequence_order}",
            'message_type': message.message_type.value,
            'sent': sent,
            'opened': opened,
            'clicked': clicked,
            'replied': replied,
            'open_rate': round((opened / sent * 100) if sent > 0 else 0, 2),
            'click_rate': round((clicked / sent * 100) if sent > 0 else 0, 2),
            'reply_rate': round((replied / sent * 100) if sent > 0 else 0, 2),
        })

    return performance


def get_lead_pipeline_metrics(db: Session, company_id: int, date_range_days: Optional[int] = 30) -> Dict[str, Any]:
    """
    Get lead pipeline metrics across all campaigns
    """
    since_date = datetime.utcnow() - timedelta(days=date_range_days) if date_range_days else None

    query = db.query(
        Lead.stage,
        func.count(Lead.id).label('count'),
        func.sum(Lead.deal_value).label('total_value'),
        func.avg(Lead.score).label('avg_score')
    ).filter(Lead.company_id == company_id)

    if since_date:
        query = query.filter(Lead.created_at >= since_date)

    pipeline_data = query.group_by(Lead.stage).all()

    metrics = {
        'by_stage': [],
        'total_leads': 0,
        'total_pipeline_value': 0,
        'avg_deal_value': 0,
        'avg_score': 0
    }

    for stage_data in pipeline_data:
        metrics['by_stage'].append({
            'stage': stage_data.stage.value,
            'count': stage_data.count,
            'total_value': float(stage_data.total_value or 0),
            'avg_score': round(float(stage_data.avg_score or 0), 2)
        })
        metrics['total_leads'] += stage_data.count
        metrics['total_pipeline_value'] += float(stage_data.total_value or 0)

    if metrics['total_leads'] > 0:
        metrics['avg_deal_value'] = metrics['total_pipeline_value'] / metrics['total_leads']

    # Calculate conversion rates between stages
    stage_counts = {stage.stage: stage.count for stage in pipeline_data}

    metrics['conversion_rates'] = {
        'lead_to_mql': round((stage_counts.get(LeadStage.MQL, 0) / stage_counts.get(LeadStage.LEAD, 1) * 100), 2),
        'mql_to_sql': round((stage_counts.get(LeadStage.SQL, 0) / stage_counts.get(LeadStage.MQL, 1) * 100), 2),
        'sql_to_opportunity': round((stage_counts.get(LeadStage.OPPORTUNITY, 0) / stage_counts.get(LeadStage.SQL, 1) * 100), 2),
        'opportunity_to_customer': round((stage_counts.get(LeadStage.CUSTOMER, 0) / stage_counts.get(LeadStage.OPPORTUNITY, 1) * 100), 2),
    }

    return metrics


def get_campaign_comparison(db: Session, company_id: int, campaign_ids: List[int]) -> List[Dict[str, Any]]:
    """
    Compare performance across multiple campaigns
    """
    comparison = []

    for campaign_id in campaign_ids:
        metrics = get_campaign_performance_metrics(db, campaign_id, company_id)
        if metrics:
            comparison.append(metrics)

    return comparison


def get_time_series_metrics(
    db: Session,
    campaign_id: int,
    company_id: int,
    metric: str = 'conversions',
    interval: str = 'day',
    days: int = 30
) -> List[Dict[str, Any]]:
    """
    Get time-series data for a specific metric
    """
    since_date = datetime.utcnow() - timedelta(days=days)

    # Map metric to activity types
    metric_map = {
        'opens': [ActivityType.EMAIL_OPENED],
        'clicks': [ActivityType.EMAIL_CLICKED],
        'replies': [ActivityType.EMAIL_REPLIED, ActivityType.SMS_REPLIED],
        'calls': [ActivityType.CALL_INITIATED],
        'conversions': [ActivityType.DEAL_WON, ActivityType.OPPORTUNITY_CREATED]
    }

    activity_types = metric_map.get(metric, [])

    # Query activities grouped by date
    if interval == 'day':
        date_trunc = func.date_trunc('day', CampaignActivity.timestamp)
    elif interval == 'week':
        date_trunc = func.date_trunc('week', CampaignActivity.timestamp)
    else:
        date_trunc = func.date_trunc('month', CampaignActivity.timestamp)

    results = db.query(
        date_trunc.label('period'),
        func.count(CampaignActivity.id).label('count')
    ).filter(
        CampaignActivity.campaign_id == campaign_id,
        CampaignActivity.timestamp >= since_date
    )

    if activity_types:
        results = results.filter(CampaignActivity.activity_type.in_(activity_types))

    results = results.group_by('period').order_by('period').all()

    return [
        {
            'period': result.period.isoformat(),
            'count': result.count
        }
        for result in results
    ]
