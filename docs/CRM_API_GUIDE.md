# AgentConnect CRM API Guide

Complete API documentation for the CRM system including Leads, Campaigns, and Scoring.

## Table of Contents
- [Leads API](#leads-api)
- [Campaigns API](#campaigns-api)
- [Lead Scoring](#lead-scoring)
- [Campaign Targeting](#campaign-targeting)
- [Workflow Integration](#workflow-integration)

---

## Leads API

Base path: `/api/v1/leads`

### 1. Create Lead
**POST** `/api/v1/leads`

Create a new lead from a contact.

```json
{
  "contact_id": 123,
  "source": "website",
  "campaign_id": 456,
  "deal_value": 10000.00,
  "expected_close_date": "2024-12-31T00:00:00Z",
  "qualification_data": {
    "company_size": "51-200",
    "industry": "technology",
    "budget_confirmed": true,
    "timeline_defined": true,
    "decision_maker_involved": true
  },
  "custom_fields": {
    "product_interest": "Enterprise Plan"
  }
}
```

**Response**: Lead object with initial stage `LEAD` and score `0`

### 2. Get Lead
**GET** `/api/v1/leads/{lead_id}`

Retrieve a single lead by ID.

**Response**:
```json
{
  "id": 1,
  "contact_id": 123,
  "company_id": 1,
  "stage": "mql",
  "score": 75,
  "qualification_status": "qualified",
  "deal_value": 10000.00,
  "assignee_id": 5,
  "created_at": "2024-01-15T10:00:00Z",
  "stage_changed_at": "2024-01-16T14:30:00Z"
}
```

### 3. Update Lead Stage
**PUT** `/api/v1/leads/{lead_id}/stage`

Transition lead to a new stage with tracking.

```json
{
  "stage": "sql",
  "stage_reason": "Budget confirmed, decision maker engaged"
}
```

**Stages**: `lead`, `mql`, `sql`, `opportunity`, `customer`, `lost`

### 4. Assign Lead
**PUT** `/api/v1/leads/{lead_id}/assign/{user_id}`

Assign lead to a sales rep.

### 5. Update Deal Value
**PUT** `/api/v1/leads/{lead_id}/deal-value`

```json
{
  "deal_value": 15000.00
}
```

### 6. Auto-Qualify Lead
**POST** `/api/v1/leads/{lead_id}/qualify?min_score_threshold=70`

Triggers automatic lead qualification based on hybrid scoring:
- Calculates AI intent score
- Calculates engagement score
- Calculates workflow score
- Computes weighted combined score
- Auto-promotes to MQL if score >= 75

**Response**: Updated lead with new score and stage

### 7. Manual Score
**POST** `/api/v1/leads/{lead_id}/score`

Set manual score from sales rep.

```json
{
  "score_value": 85,
  "reason": "High-value enterprise prospect with clear budget"
}
```

### 8. Get Score Breakdown
**GET** `/api/v1/leads/{lead_id}/scores`

Get detailed breakdown of all scoring components.

**Response**:
```json
{
  "lead_id": 1,
  "scores_by_type": {
    "ai_intent": {
      "latest_score": 82,
      "latest_scored_at": "2024-01-15T10:00:00Z",
      "reason": "Analyzed 5 conversation intents with average confidence 82%",
      "confidence": 0.82,
      "factors": {
        "intent_count": 5,
        "intents": [...]
      }
    },
    "engagement": {
      "latest_score": 65,
      "factors": {
        "opens": 8,
        "clicks": 4,
        "replies": 2,
        "calls_completed": 1
      }
    },
    "demographic": {
      "latest_score": 75,
      "factors": {
        "demographics": {
          "company_size": {"value": "51-200", "points": 60},
          "industry": {"value": "technology", "points": 90}
        }
      }
    },
    "workflow": {
      "latest_score": 100,
      "factors": {
        "completion_percentage": 100,
        "answered_questions": 3
      }
    },
    "combined": {
      "latest_score": 78
    }
  },
  "latest_combined_score": 78
}
```

### 9. Search Leads
**GET** `/api/v1/leads/search?query=tech&stage=mql&min_score=70`

Search and filter leads.

**Query Parameters**:
- `query`: Text search (contact name, email)
- `stage`: Filter by stage
- `min_score`, `max_score`: Score range
- `assignee_id`: Filter by assignee
- `qualification_status`: `qualified`, `unqualified`, `disqualified`
- `skip`, `limit`: Pagination

### 10. Lead Statistics
**GET** `/api/v1/leads/stats`

Get aggregated statistics.

**Response**:
```json
{
  "total_leads": 150,
  "lead_count": 45,
  "mql_count": 38,
  "sql_count": 25,
  "opportunity_count": 20,
  "customer_count": 18,
  "lost_count": 4,
  "avg_score": 67.5,
  "total_pipeline_value": 450000.00,
  "qualified_count": 83,
  "unqualified_count": 42
}
```

---

## Campaigns API

Base path: `/api/v1/campaigns`

### 1. Create Campaign
**POST** `/api/v1/campaigns`

```json
{
  "name": "Q4 Product Launch Campaign",
  "description": "Multi-channel outreach for enterprise prospects",
  "campaign_type": "multi_channel",
  "target_criteria": {
    "lifecycle_stages": ["lead", "mql"],
    "min_lead_score": 60,
    "lead_sources": ["website", "referral"],
    "tags": ["product-interest", "enterprise"],
    "exclude_do_not_contact": true,
    "exclude_already_enrolled": true,
    "max_contacts": 500
  },
  "goal_type": "conversion",
  "goal_value": 50,
  "budget": 10000.00,
  "start_date": "2024-02-01T00:00:00Z",
  "end_date": "2024-03-31T23:59:59Z",
  "workflow_id": 10,
  "agent_id": 5,
  "settings": {
    "send_time_optimization": true,
    "frequency_cap": "1_per_day"
  }
}
```

**Campaign Types**:
- `email` - Email marketing
- `sms` - SMS messaging
- `whatsapp` - WhatsApp messaging
- `voice` - Twilio voice calls
- `multi_channel` - Sequence across channels

**Goal Types**:
- `lead_generation`
- `nurture`
- `conversion`
- `engagement`
- `retention`

### 2. Get Campaign
**GET** `/api/v1/campaigns/{campaign_id}`

### 3. List Campaigns
**GET** `/api/v1/campaigns?status=active&type=email`

**Query Parameters**:
- `status`: `draft`, `active`, `paused`, `completed`, `archived`
- `type`: Campaign type filter
- `skip`, `limit`: Pagination

### 4. Update Campaign
**PATCH** `/api/v1/campaigns/{campaign_id}`

Update campaign fields.

### 5. Delete Campaign
**DELETE** `/api/v1/campaigns/{campaign_id}`

Soft delete (archives) the campaign.

### 6. Enroll Contacts
**POST** `/api/v1/campaigns/{campaign_id}/enroll`

Manually enroll specific contacts.

```json
{
  "contact_ids": [101, 102, 103]
}
```

### 7. Auto-Enroll from Criteria
**POST** `/api/v1/campaigns/{campaign_id}/enroll-from-criteria`

Automatically enroll all contacts matching the campaign's target criteria.

**Response**:
```json
{
  "enrolled_count": 145,
  "enrollments": [...]
}
```

### 8. Get Targeted Contacts (Preview)
**GET** `/api/v1/campaigns/{campaign_id}/targeted-contacts`

Preview contacts that match targeting criteria without enrolling them.

### 9. Get Campaign Contacts
**GET** `/api/v1/campaigns/{campaign_id}/contacts?status=pending`

Get all enrolled contacts with their status.

**Status Values**: `pending`, `active`, `paused`, `completed`, `bounced`, `unsubscribed`

### 10. Unenroll Contact
**POST** `/api/v1/campaigns/{campaign_id}/unenroll/{contact_id}`

Remove contact from campaign.

### 11. Campaign Messages
**GET** `/api/v1/campaigns/{campaign_id}/messages`

Get all messages in campaign sequence.

**POST** `/api/v1/campaigns/{campaign_id}/messages`

Add message to sequence.

```json
{
  "step_number": 1,
  "message_type": "email",
  "subject": "Introducing Our New Enterprise Features",
  "content": "Hi {{first_name}},\n\nWe noticed you've been exploring...",
  "delay_amount": 0,
  "delay_unit": "days",
  "send_time": "09:00:00"
}
```

**Message Types**: `email`, `sms`, `whatsapp`, `voice`

**Delay Units**: `minutes`, `hours`, `days`, `weeks`

**Personalization Tokens**:
- `{{first_name}}` - Contact's first name
- `{{name}}` - Full name
- `{{email}}` - Email address
- `{{company}}` - Company name
- `{{deal_value}}` - Lead deal value
- `{{score}}` - Lead score

### 12. Update Message
**PATCH** `/api/v1/campaigns/{campaign_id}/messages/{message_id}`

### 13. Delete Message
**DELETE** `/api/v1/campaigns/{campaign_id}/messages/{message_id}`

### 14. Start Campaign
**POST** `/api/v1/campaigns/{campaign_id}/start`

Activate campaign and begin sending messages.

### 15. Pause Campaign
**POST** `/api/v1/campaigns/{campaign_id}/pause`

### 16. Resume Campaign
**POST** `/api/v1/campaigns/{campaign_id}/resume`

### 17. Campaign Performance
**GET** `/api/v1/campaigns/{campaign_id}/performance`

Get comprehensive metrics.

**Response**:
```json
{
  "campaign_id": 1,
  "total_enrolled": 500,
  "emails_sent": 1200,
  "emails_delivered": 1150,
  "emails_opened": 450,
  "emails_clicked": 180,
  "open_rate": 39.13,
  "click_rate": 15.65,
  "sms_sent": 300,
  "sms_delivered": 295,
  "calls_initiated": 50,
  "calls_completed": 38,
  "conversions": 12,
  "conversion_rate": 2.4,
  "total_revenue": 180000.00,
  "actual_cost": 2500.00,
  "roi": 7100.0,
  "avg_response_time_hours": 4.5
}
```

### 18. Campaign Funnel
**GET** `/api/v1/campaigns/{campaign_id}/funnel`

Get conversion funnel visualization data.

**Response**:
```json
{
  "stages": [
    {"stage": "enrolled", "count": 500, "percentage": 100},
    {"stage": "delivered", "count": 480, "percentage": 96},
    {"stage": "opened", "count": 280, "percentage": 56},
    {"stage": "clicked", "count": 120, "percentage": 24},
    {"stage": "replied", "count": 45, "percentage": 9},
    {"stage": "converted", "count": 12, "percentage": 2.4}
  ]
}
```

### 19. Campaign Activities
**GET** `/api/v1/campaigns/{campaign_id}/activities?type=email_opened&limit=50`

Get activity log for campaign.

**Activity Types**:
- `email_sent`, `email_delivered`, `email_opened`, `email_clicked`, `email_replied`
- `sms_sent`, `sms_delivered`, `sms_replied`
- `call_initiated`, `call_completed`, `voicemail_detected`
- `link_clicked`, `form_submitted`, `meeting_scheduled`
- `deal_won`, `deal_lost`

---

## Lead Scoring

The CRM implements a hybrid lead scoring system with 7 score types:

### Score Types

1. **AI Intent Score** (`ai_intent`)
   - Analyzes conversation transcripts for purchase intent
   - Detects keywords: buy, pricing, demo, trial, enterprise
   - Boosts for urgency indicators
   - Range: 0-100, confidence-weighted

2. **Engagement Score** (`engagement`)
   - Email opens (max 30 points)
   - Link clicks (max 30 points)
   - Replies (max 25 points)
   - Calls completed (max 15 points)
   - Based on 30-day lookback

3. **Demographic Score** (`demographic`)
   - Company size scoring
   - Industry fit
   - Job role/title
   - Customizable scoring rules

4. **Behavioral Score** (`behavioral`)
   - Website visits
   - Content downloads
   - Page views
   - Time on site

5. **Workflow Score** (`workflow`)
   - Qualification question completion
   - Budget confirmation (+15)
   - Timeline defined (+15)
   - Decision maker involved (+20)

6. **Manual Score** (`manual`)
   - Set by sales rep
   - Override for special cases
   - Includes reasoning

7. **Combined Score** (`combined`)
   - Weighted average of all scores
   - Default weights:
     - AI Intent: 25%
     - Engagement: 25%
     - Demographic: 15%
     - Workflow: 20%
     - Manual: 15%

### Auto-Qualification Rules

- Score >= 70: `QUALIFIED`
- Score >= 75: Auto-promote to `MQL`
- Score < 40: `DISQUALIFIED`

---

## Campaign Targeting

### Target Criteria Object

```json
{
  "lifecycle_stages": ["lead", "mql"],
  "lead_stages": ["lead", "mql", "sql"],
  "min_lead_score": 60,
  "max_lead_score": 100,
  "lead_sources": ["website", "referral", "event"],
  "tags": ["product-interest", "enterprise"],
  "opt_in_status": "opted_in",
  "exclude_do_not_contact": true,
  "exclude_already_enrolled": true,
  "max_contacts": 1000
}
```

### Smart Targeting Features

- **Lifecycle Stage Filtering**: Target by contact lifecycle
- **Lead Score Range**: Only high-quality leads
- **Source Attribution**: Target specific channels
- **Tag-based Segmentation**: Tag arrays with JSON containment
- **Compliance**: Auto-exclude do-not-contact
- **Deduplication**: Prevent multiple enrollments

---

## Workflow Integration

### Campaign with Workflow

When a campaign is linked to a workflow:

```json
{
  "campaign_type": "multi_channel",
  "workflow_id": 15,
  "agent_id": 8
}
```

The workflow defines the logic flow, and the agent handles AI conversations.

### Voice Campaign with AI Agent

```json
{
  "campaign_type": "voice",
  "agent_id": 8,
  "twilio_config": {
    "account_sid": "AC...",
    "phone_number": "+15551234567",
    "use_ai_agent": true,
    "voicemail_detection": true,
    "recording_enabled": true
  }
}
```

Campaign message for voice:

```json
{
  "message_type": "voice",
  "voice_script": "Hi {{first_name}}, this is Sarah calling about...",
  "tts_voice_id": "en-US-Neural2-F",
  "voice_agent_id": 8,
  "call_flow_config": {
    "max_duration_seconds": 300,
    "enable_dtmf": true,
    "transfer_number": "+15559876543"
  }
}
```

---

## Best Practices

### Lead Management

1. **Create leads immediately** when contacts show interest
2. **Set qualification_data** early for better demographic scoring
3. **Run auto-qualification** after each significant interaction
4. **Assign leads promptly** to prevent aging

### Campaign Design

1. **Start with targeting criteria** - Be specific
2. **Build message sequences** - 3-5 touchpoints optimal
3. **Use personalization tokens** - Higher engagement
4. **Test with small group** first before full rollout
5. **Monitor metrics daily** during active campaigns

### Scoring Optimization

1. **Customize demographic rules** for your ICP
2. **Adjust weights** based on what predicts conversions
3. **Review manual scores** for pattern insights
4. **Set qualification threshold** based on sales capacity

### Compliance

1. **Always respect do_not_contact** flags
2. **Check opt_in_status** before messaging
3. **Honor unsubscribe requests** immediately
4. **Log all consent changes**

---

## Error Codes

- `400` - Invalid request (check required fields)
- `404` - Lead/Campaign not found
- `403` - Unauthorized (wrong company_id)
- `409` - Conflict (duplicate enrollment)
- `422` - Validation error (invalid enum values)

---

## Webhooks

### Campaign Events

Configure webhooks to receive campaign event notifications:

```json
POST /api/v1/webhooks
{
  "url": "https://your-app.com/webhook",
  "events": [
    "campaign.started",
    "campaign.completed",
    "contact.enrolled",
    "contact.converted",
    "message.sent",
    "message.opened",
    "message.clicked"
  ]
}
```

---

## Rate Limits

- API calls: 1000 requests/minute per company
- Campaign enrollment: 10,000 contacts/batch
- Message sending: Based on Twilio/provider limits

---

For questions or support, contact the AgentConnect team.
