# CRM Quick Start Guide

## 🚀 5-Minute Setup

### Database Migration
```bash
cd backend
source venv/bin/activate
alembic upgrade head
```

### Verify Installation
```bash
python test_crm_system.py
```

---

## 📚 Common Use Cases

### 1. Create a Lead from Contact

```bash
POST /api/v1/leads
```
```json
{
  "contact_id": 123,
  "source": "website",
  "deal_value": 10000,
  "qualification_data": {
    "company_size": "51-200",
    "industry": "technology"
  }
}
```

### 2. Auto-Qualify Lead

```bash
POST /api/v1/leads/1/qualify?min_score_threshold=70
```

Returns updated lead with:
- AI intent score
- Engagement score
- Demographic score
- Workflow score
- Combined score
- Auto-qualification status
- Auto-stage promotion if score ≥ 75

### 3. Create Email Campaign

```bash
POST /api/v1/campaigns
```
```json
{
  "name": "Q4 Product Launch",
  "campaign_type": "email",
  "target_criteria": {
    "lifecycle_stages": ["lead", "mql"],
    "min_lead_score": 60
  },
  "goal_type": "conversion",
  "goal_value": 50
}
```

### 4. Add Campaign Message

```bash
POST /api/v1/campaigns/1/messages
```
```json
{
  "step_number": 1,
  "message_type": "email",
  "subject": "Hi {{first_name}} - Special Offer",
  "content": "Hi {{first_name}},\n\nWe have a special offer...",
  "delay_amount": 0,
  "delay_unit": "days"
}
```

### 5. Enroll Contacts Automatically

```bash
POST /api/v1/campaigns/1/enroll-from-criteria
```

Automatically enrolls all contacts matching the campaign's targeting criteria.

### 6. Start Campaign

```bash
POST /api/v1/campaigns/1/start
```

### 7. Get Performance Metrics

```bash
GET /api/v1/campaigns/1/performance
```

Returns:
- Open/click rates
- Conversion rate
- Revenue
- ROI
- Engagement metrics

---

## 🎯 Common Queries

### Get Unassigned High-Score Leads
```bash
GET /api/v1/leads/unassigned?min_score=70
```

### Get Leads by Stage
```bash
GET /api/v1/leads/by-stage/mql
```

### Get Active Campaigns
```bash
GET /api/v1/campaigns/active
```

### Get Campaign Summary
```bash
GET /api/v1/campaigns/1/summary
```

### Bulk Assign Leads
```bash
POST /api/v1/leads/bulk-assign
```
```json
{
  "lead_ids": [1, 2, 3, 4, 5],
  "assignee_id": 10
}
```

---

## 🔑 Personalization Tokens

Use in campaign messages:

- `{{first_name}}` - Contact's first name
- `{{name}}` - Full name
- `{{email}}` - Email address
- `{{company}}` - Company name
- `{{deal_value}}` - Lead deal value
- `{{score}}` - Lead score

---

## 📊 Scoring System

### Score Types & Weights

| Type | Weight | Description |
|------|--------|-------------|
| AI Intent | 25% | Conversation analysis |
| Engagement | 25% | Opens, clicks, replies |
| Demographic | 15% | Company fit |
| Workflow | 20% | Qualification completion |
| Manual | 15% | Sales rep override |

### Auto-Qualification

- Score ≥ 70 → QUALIFIED
- Score ≥ 75 → Auto-promote to MQL
- Score < 40 → DISQUALIFIED

---

## 🎬 Pipeline Stages

1. **lead** - Initial contact
2. **mql** - Marketing qualified
3. **sql** - Sales qualified
4. **opportunity** - Active deal
5. **customer** - Won
6. **lost** - Closed lost

---

## 🎯 Campaign Types

- `email` - Email marketing
- `sms` - SMS messaging
- `whatsapp` - WhatsApp
- `voice` - Twilio calls
- `multi_channel` - Combined sequence

---

## 📞 Voice Campaigns

### Create Voice Campaign

```json
{
  "campaign_type": "voice",
  "agent_id": 8,
  "twilio_config": {
    "account_sid": "AC...",
    "phone_number": "+15551234567",
    "use_ai_agent": true,
    "voicemail_detection": true
  }
}
```

### Voice Message

```json
{
  "message_type": "voice",
  "voice_script": "Hi {{first_name}}, this is...",
  "tts_voice_id": "en-US-Neural2-F",
  "voice_agent_id": 8,
  "call_flow_config": {
    "max_duration_seconds": 300,
    "enable_dtmf": true
  }
}
```

---

## 🎨 Targeting Criteria

```json
{
  "lifecycle_stages": ["lead", "mql"],
  "lead_stages": ["lead", "mql", "sql"],
  "min_lead_score": 60,
  "max_lead_score": 100,
  "lead_sources": ["website", "referral"],
  "tags": ["product-interest"],
  "exclude_do_not_contact": true,
  "exclude_already_enrolled": true,
  "max_contacts": 1000
}
```

---

## 🔍 Search & Filter

### Leads
```bash
GET /api/v1/leads?stage=mql&min_score=70&assignee_id=5
```

### Campaigns
```bash
GET /api/v1/campaigns?status=active&type=email
```

---

## 📈 Analytics Endpoints

```bash
# Lead statistics
GET /api/v1/leads/stats

# Campaign performance
GET /api/v1/campaigns/{id}/performance

# Campaign funnel
GET /api/v1/campaigns/{id}/funnel

# Compare campaigns
POST /api/v1/campaigns/analytics/compare
{
  "campaign_ids": [1, 2, 3]
}
```

---

## ⚡ Bulk Operations

```bash
# Bulk assign
POST /api/v1/leads/bulk-assign

# Bulk update stage
POST /api/v1/leads/bulk-update-stage
```

---

## 🧪 Testing

```bash
# Test campaign preview
POST /api/v1/campaigns/{id}/test-send?test_contact_id=123

# Clone campaign
POST /api/v1/campaigns/{id}/clone?new_name=Copy+of+Campaign
```

---

## 🚨 Important Notes

### Authentication
All endpoints require:
```
Authorization: Bearer {token}
```

### Company Isolation
All queries automatically filter by `current_user.company_id`

### Compliance
- Always check `do_not_contact` flag
- Respect `opt_in_status`
- Log consent changes

### Rate Limits
- API: 1000 req/min per company
- Enrollment: 10,000 contacts/batch
- Sending: Per provider limits

---

## 📖 Full Documentation

- **Complete API Guide**: `docs/CRM_API_GUIDE.md`
- **Implementation Details**: `docs/CRM_IMPLEMENTATION_SUMMARY.md`

---

## 🆘 Troubleshooting

### Common Issues

**Lead not auto-qualifying:**
- Check if all score types calculated
- Verify threshold setting
- Check qualification_data present

**Campaign not sending:**
- Verify status is ACTIVE
- Check messages exist
- Confirm contacts enrolled

**Targeting returns no contacts:**
- Check criteria values (lowercase for enums)
- Verify contacts have leads created
- Check do_not_contact status

---

## 💡 Pro Tips

1. **Start small** - Test with 10-20 contacts first
2. **Use test-send** - Preview before launching
3. **Clone campaigns** - Reuse what works
4. **Monitor daily** - Check metrics during active campaigns
5. **Adjust thresholds** - Optimize based on conversion data

---

**Happy CRM-ing!** 🎉
