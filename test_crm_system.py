"""
Test script for CRM system functionality
Tests leads, campaigns, scoring, and analytics
"""
import asyncio
from sqlalchemy.orm import Session
from app.core.database import SessionLocal, engine
from app.models import Company, User, Contact, Lead, Campaign, Agent
from app.models.lead import LeadStage, QualificationStatus
from app.models.campaign import CampaignType, CampaignStatus
from app.services import lead_service, campaign_service, lead_qualification_service
from app.schemas.lead import LeadCreate, LeadUpdate
from app.schemas.campaign import CampaignCreate
from datetime import datetime


def create_test_data(db: Session):
    """Create test company, user, and contacts"""
    print("\n1. Creating test data...")

    # Create or get test company
    company = db.query(Company).filter(Company.name == "Test CRM Company").first()
    if not company:
        company = Company(name="Test CRM Company")
        db.add(company)
        db.commit()
        db.refresh(company)
    print(f"   ✓ Company created: {company.name} (ID: {company.id})")

    # Create or get test user
    user = db.query(User).filter(User.email == "crm-test@example.com").first()
    if not user:
        user = User(
            email="crm-test@example.com",
            hashed_password="test_hash",
            first_name="CRM Test",
            last_name="User",
            company_id=company.id,
            is_active=True
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    print(f"   ✓ User created: {user.first_name} {user.last_name} (ID: {user.id})")

    # Create test contacts
    contacts = []
    contact_data = [
        {"name": "John Smith", "email": "john@example.com", "phone": "+1234567890"},
        {"name": "Jane Doe", "email": "jane@example.com", "phone": "+1234567891"},
        {"name": "Bob Johnson", "email": "bob@example.com", "phone": "+1234567892"},
    ]

    for data in contact_data:
        contact = db.query(Contact).filter(
            Contact.email == data["email"],
            Contact.company_id == company.id
        ).first()

        if not contact:
            contact = Contact(
                company_id=company.id,
                name=data["name"],
                email=data["email"],
                phone_number=data["phone"],
                lead_source="website"
            )
            db.add(contact)
            db.commit()
            db.refresh(contact)
        contacts.append(contact)

    print(f"   ✓ Created {len(contacts)} contacts")

    return company, user, contacts


def test_lead_management(db: Session, company, user, contacts):
    """Test lead creation and management"""
    print("\n2. Testing Lead Management...")

    # Create leads from contacts
    leads = []
    for contact in contacts:
        # Check if lead already exists
        existing_lead = db.query(Lead).filter(
            Lead.contact_id == contact.id,
            Lead.company_id == company.id
        ).first()

        if existing_lead:
            lead = existing_lead
        else:
            lead_data = LeadCreate(
                contact_id=contact.id,
                source="website",
                deal_value=10000.00,
                expected_close_date=datetime.utcnow(),
                qualification_data={
                    "company_size": "51-200",
                    "industry": "technology",
                    "budget_confirmed": True
                }
            )
            lead = lead_service.create_lead(db, lead_data, company.id)
        leads.append(lead)

    print(f"   ✓ Created {len(leads)} leads")

    # Test lead stage update
    if leads:
        lead = leads[0]
        print(f"   - Lead {lead.id} current stage: {lead.stage}")

        # Update to MQL
        from app.schemas.lead import LeadStageUpdate
        stage_update = LeadStageUpdate(
            stage=LeadStage.MQL,
            stage_reason="High engagement score"
        )
        updated_lead = lead_service.update_lead_stage(db, lead.id, stage_update, company.id)
        print(f"   ✓ Updated lead {lead.id} to stage: {updated_lead.stage}")

    # Test lead assignment
    if leads and user:
        lead = leads[1]
        assigned_lead = lead_service.assign_lead(db, lead.id, user.id, company.id)
        print(f"   ✓ Assigned lead {lead.id} to user {user.id}")

    # Get lead statistics
    stats = lead_service.get_lead_stats(db, company.id)
    print(f"   ✓ Lead statistics: {stats['total_leads']} total leads")

    return leads


def test_lead_scoring(db: Session, company, leads):
    """Test lead scoring system"""
    print("\n3. Testing Lead Scoring System...")

    if not leads:
        print("   ⚠ No leads to score")
        return

    lead = leads[0]

    # Test demographic scoring
    demo_score = lead_qualification_service.calculate_demographic_score(db, lead.id)
    if demo_score:
        print(f"   ✓ Demographic score: {demo_score.score_value}/100")

    # Test workflow scoring
    workflow_score = lead_qualification_service.calculate_workflow_score(db, lead.id)
    if workflow_score:
        print(f"   ✓ Workflow score: {workflow_score.score_value}/100")

    # Test combined scoring and auto-qualification
    qualified_lead = lead_qualification_service.auto_qualify_lead(db, lead.id, min_score_threshold=60)
    print(f"   ✓ Lead {lead.id} auto-qualified:")
    print(f"     - Score: {qualified_lead.score}/100")
    print(f"     - Status: {qualified_lead.qualification_status}")
    print(f"     - Stage: {qualified_lead.stage}")

    # Get scoring breakdown
    breakdown = lead_qualification_service.get_lead_scoring_breakdown(db, lead.id)
    print(f"   ✓ Scoring breakdown: {len(breakdown['scores_by_type'])} score types")
    for score_type, details in breakdown['scores_by_type'].items():
        print(f"     - {score_type}: {details['latest_score']}/100")


def test_campaign_management(db: Session, company, user, contacts, leads):
    """Test campaign creation and management"""
    print("\n4. Testing Campaign Management...")

    # Create email campaign
    campaign_data = CampaignCreate(
        name="Q4 Product Launch Campaign",
        description="Email campaign for Q4 product launch",
        campaign_type=CampaignType.EMAIL,
        target_criteria={
            "lifecycle_stages": ["lead", "mql"],
            "min_lead_score": 50,
            "tags": ["product-interest"]
        },
        goal_type="conversion",
        goal_value=100,
        start_date=datetime.utcnow(),
        created_by_user_id=user.id,
        owner_user_id=user.id
    )

    campaign = campaign_service.create_campaign(db, campaign_data, company.id, user.id)
    print(f"   ✓ Created campaign: {campaign.name} (ID: {campaign.id})")
    print(f"     - Type: {campaign.campaign_type}")
    print(f"     - Status: {campaign.status}")

    # Test contact enrollment
    if leads:
        enrolled = campaign_service.enroll_contacts(
            db,
            campaign.id,
            [lead.contact_id for lead in leads[:2]],
            company.id
        )
        print(f"   ✓ Enrolled {len(enrolled)} contacts in campaign")

        for enrollment in enrolled:
            print(f"     - Contact {enrollment.contact_id}: {enrollment.status}")

    # Get campaign enrollments
    enrollments = campaign_service.get_campaign_contacts(db, campaign.id, company.id)
    print(f"   ✓ Total enrollments: {len(enrollments)}")

    # Update campaign status
    campaign.status = CampaignStatus.ACTIVE
    db.commit()
    print(f"   ✓ Campaign status updated to: {campaign.status}")

    return campaign


def test_campaign_targeting(db: Session, company, campaign):
    """Test smart contact targeting"""
    print("\n5. Testing Smart Contact Targeting...")

    # Get targeted contacts based on criteria
    targeted = campaign_service.get_targeted_contacts(db, campaign.id, company.id)
    print(f"   ✓ Found {len(targeted)} contacts matching criteria:")

    for contact in targeted[:3]:
        print(f"     - {contact.name} ({contact.email})")
        print(f"       Lifecycle: {contact.lifecycle_stage}")


def main():
    """Run all CRM system tests"""
    print("=" * 60)
    print("CRM SYSTEM TEST SUITE")
    print("=" * 60)

    db = SessionLocal()
    try:
        # Create test data
        company, user, contacts = create_test_data(db)

        # Test lead management
        leads = test_lead_management(db, company, user, contacts)

        # Test lead scoring
        test_lead_scoring(db, company, leads)

        # Test campaign management
        campaign = test_campaign_management(db, company, user, contacts, leads)

        # Test campaign targeting
        test_campaign_targeting(db, company, campaign)

        print("\n" + "=" * 60)
        print("✅ ALL TESTS COMPLETED SUCCESSFULLY!")
        print("=" * 60)

    except Exception as e:
        print(f"\n❌ ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    main()
