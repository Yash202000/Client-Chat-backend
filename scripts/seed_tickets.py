"""
End-to-end ticket system test seed.

Creates:
  • 5 users  — 1 citizen, 2 agents, 1 supervisor, 1 contractor
  • 2 departments (Infrastructure & Public Works | Health & Civic Services)
    each department gets classification nodes assigned
  • 1 ticket project  "Citizen Grievance Portal"  (key: GRV)
  • Custom civic workflow with 7 statuses and 9 transitions
  • 2 routing rules  (dept-based round-robin by classification)
  • 5 test tickets filed by the citizen
  • Transitions performed by agents / supervisor / contractor

Run from backend/:
    python scripts/seed_tickets.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime
from passlib.context import CryptContext

from app.core.database import SessionLocal
from app.models.user import User
from app.models.ticket_project import TicketProject
from app.models.ticket_workflow import TicketWorkflow, TicketStatus, TicketTransition, StatusCategory
from app.models.ticket import Ticket, TicketActivity, TicketActivityAction
from app.models.ticket_issue_type import TicketIssueType
from app.models.hierarchy import HierarchyType, HierarchyNode
from app.models.department import Department, DepartmentNodeAssignment, DepartmentUserMembership
from app.models.routing_rule import RoutingRule
from app.services.ticket_service import seed_company_defaults, execute_transition
from app.schemas.ticket import TicketTransitionExecute

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

COMPANY_ID = 1
DEFAULT_PASS = "Test@1234"


# ─── helpers ──────────────────────────────────────────────────────────────────

def upsert_user(db, email, first, last, title, is_admin=False):
    u = db.query(User).filter_by(email=email).first()
    if u:
        print(f"  skip user: {email}")
        return u
    u = User(
        company_id=COMPANY_ID,
        email=email,
        hashed_password=pwd.hash(DEFAULT_PASS),
        first_name=first,
        last_name=last,
        job_title=title,
        is_admin=is_admin,
        is_active=True,
    )
    db.add(u)
    db.flush()
    print(f"  created user: {email}  ({title})  id={u.id}")
    return u


def get_node(db, code):
    n = db.query(HierarchyNode).filter_by(company_id=COMPANY_ID, code=code).first()
    if not n:
        raise RuntimeError(f"Node with code '{code}' not found. Run seed_hierarchy.py first.")
    return n


def get_hierarchy_type(db, name):
    ht = db.query(HierarchyType).filter_by(company_id=COMPANY_ID, name=name).first()
    if not ht:
        raise RuntimeError(f"Hierarchy type '{name}' not found. Run seed_hierarchy.py first.")
    return ht


def upsert_dept(db, name, description):
    d = db.query(Department).filter_by(company_id=COMPANY_ID, name=name).first()
    if d:
        print(f"  skip dept: {name}")
        return d
    d = Department(
        company_id=COMPANY_ID,
        name=name,
        description=description,
        is_active=True,
    )
    db.add(d)
    db.flush()
    print(f"  created dept: {name}  id={d.id}")
    return d


def assign_node_to_dept(db, dept, node_code):
    node = get_node(db, node_code)
    exists = db.query(DepartmentNodeAssignment).filter_by(
        department_id=dept.id, node_id=node.id
    ).first()
    if exists:
        return
    db.add(DepartmentNodeAssignment(
        company_id=COMPANY_ID,
        department_id=dept.id,
        node_id=node.id,
    ))
    print(f"    node {node_code} → dept {dept.name}")


def add_dept_member(db, dept, user, role):
    exists = db.query(DepartmentUserMembership).filter_by(
        department_id=dept.id, user_id=user.id, role=role
    ).first()
    if exists:
        return
    db.add(DepartmentUserMembership(
        company_id=COMPANY_ID,
        department_id=dept.id,
        user_id=user.id,
        role=role,
    ))
    print(f"    user {user.email} ({role}) → dept {dept.name}")


def find_status(db, workflow_id, name):
    s = db.query(TicketStatus).filter_by(workflow_id=workflow_id, name=name).first()
    if not s:
        raise RuntimeError(f"Status '{name}' not found in workflow {workflow_id}")
    return s


def find_transition(db, workflow_id, name, from_name=None):
    q = db.query(TicketTransition).filter_by(workflow_id=workflow_id, name=name)
    if from_name:
        fs = find_status(db, workflow_id, from_name)
        q = q.filter_by(from_status_id=fs.id)
    t = q.first()
    if not t:
        raise RuntimeError(f"Transition '{name}' not found")
    return t


def create_ticket(db, project, workflow, reporter, title, desc,
                  classification_code, location_code, priority="medium"):
    filed_status = find_status(db, workflow.id, "Filed")
    issue_type = db.query(TicketIssueType).filter_by(
        company_id=COMPANY_ID, name="Task"
    ).first()

    project.ticket_counter += 1
    ticket_number = f"{project.key}-{project.ticket_counter}"

    t = Ticket(
        company_id=COMPANY_ID,
        project_id=project.id,
        ticket_number=ticket_number,
        title=title,
        description=desc,
        status_id=filed_status.id,
        issue_type_id=issue_type.id if issue_type else None,
        priority=priority,
        reporter_id=reporter.id,
        custom_fields={"classification": classification_code, "location": location_code},
        position=float(project.ticket_counter),
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(t)
    db.flush()
    db.add(TicketActivity(
        ticket_id=t.id, actor_id=reporter.id,
        action=TicketActivityAction.CREATED,
        created_at=datetime.utcnow(),
    ))
    print(f"  created ticket {ticket_number}: [{classification_code} @ {location_code}] {title}")
    return t


def do_transition(db, ticket, workflow_id, actor, transition_name, from_status_name=None, comment=None):
    t = find_transition(db, workflow_id, transition_name, from_status_name)
    data = TicketTransitionExecute(
        transition_id=t.id,
        comment=comment,
        field_values={},
    )
    try:
        result = execute_transition(db, ticket.id, data, COMPANY_ID, actor.id)
        if result:
            new_status = db.query(TicketStatus).filter_by(id=result.status_id).first()
            print(f"  [{ticket.ticket_number}] '{transition_name}' by {actor.first_name} → {new_status.name if new_status else '?'}")
        return result
    except Exception as e:
        print(f"  [{ticket.ticket_number}] transition '{transition_name}' FAILED: {e}")
        return None


# ─── main ─────────────────────────────────────────────────────────────────────

def main():
    db = SessionLocal()
    try:
        print("\n═══ 1. Seed company defaults (workflow + issue types) ═══")
        seed_company_defaults(db, COMPANY_ID)

        # ── Users ──────────────────────────────────────────────────────────────
        print("\n═══ 2. Users ═══")
        citizen  = upsert_user(db, "riya.sharma@grv.test",   "Riya",   "Sharma", "Citizen")
        agent1   = upsert_user(db, "arun.mehta@grv.test",    "Arun",   "Mehta",  "Field Agent")
        super1   = upsert_user(db, "priya.nair@grv.test",    "Priya",  "Nair",   "Supervisor")
        contract = upsert_user(db, "vikram.patel@grv.test",  "Vikram", "Patel",  "Contractor")
        agent2   = upsert_user(db, "sneha.joshi@grv.test",   "Sneha",  "Joshi",  "Field Agent")
        db.flush()

        # ── Departments ────────────────────────────────────────────────────────
        print("\n═══ 3. Departments ═══")
        infra_dept = upsert_dept(db, "Infrastructure & Public Works",
                                 "Handles roads, water, electricity complaints")
        health_dept = upsert_dept(db, "Health & Civic Services",
                                  "Handles health, civic and law & order complaints")
        db.flush()

        print("  Assigning classification nodes →")
        # Infra dept — classification
        for code in ["infra", "infra_roads", "infra_water", "infra_elec",
                     "infra_roads_pothole", "infra_roads_streetlight", "infra_roads_traffic",
                     "infra_water_pipe", "infra_water_sewage", "infra_water_nosupply",
                     "infra_elec_outage", "infra_elec_transformer"]:
            assign_node_to_dept(db, infra_dept, code)
        # Health dept — classification
        for code in ["health", "health_garbage", "health_mosquito",
                     "health_food", "health_food_restaurant", "health_food_market",
                     "civic", "civic_birth", "civic_death", "civic_propertytax", "civic_buildingpermit",
                     "law", "law_noise", "law_encroach", "law_illegalconstruct"]:
            assign_node_to_dept(db, health_dept, code)

        print("  Assigning location nodes →")
        # Infra dept — Maharashtra (Mumbai + Pune + Nagpur)
        for code in ["in_mh", "in_mh_mum", "in_mh_mum_andheri", "in_mh_mum_bandra", "in_mh_mum_dadar",
                     "in_mh_pune", "in_mh_pune_kothrud", "in_mh_pune_wakad", "in_mh_nagpur"]:
            assign_node_to_dept(db, infra_dept, code)
        # Health dept — Karnataka + Tamil Nadu
        for code in ["in_ka", "in_ka_blr", "in_ka_blr_koramangala", "in_ka_blr_whitefield", "in_ka_mys",
                     "in_tn", "in_tn_che", "in_tn_cbe"]:
            assign_node_to_dept(db, health_dept, code)
        db.flush()

        print("  Adding department members →")
        add_dept_member(db, infra_dept,  agent1,   "agent")
        add_dept_member(db, infra_dept,  super1,   "supervisor")
        add_dept_member(db, health_dept, contract, "agent")   # contractor acts as agent here
        add_dept_member(db, health_dept, agent2,   "agent")
        add_dept_member(db, health_dept, super1,   "supervisor")  # supervisor oversees both
        db.flush()

        # ── Custom Civic Workflow ──────────────────────────────────────────────
        print("\n═══ 4. Civic Grievance Workflow ═══")
        existing_wf = db.query(TicketWorkflow).filter_by(
            company_id=COMPANY_ID, name="Civic Grievance Workflow"
        ).first()

        if existing_wf:
            wf = existing_wf
            print(f"  skip workflow (exists, id={wf.id})")
        else:
            wf = TicketWorkflow(
                company_id=COMPANY_ID,
                name="Civic Grievance Workflow",
                description="Complaint lifecycle: citizen files → field work → supervisor approval",
                is_default=False,
                entity_type=None,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            db.add(wf)
            db.flush()

            statuses_data = [
                {"name": "Filed",            "color": "#94a3b8", "category": StatusCategory.TODO,        "position": 0, "is_default": True},
                {"name": "Assigned",         "color": "#3b82f6", "category": StatusCategory.IN_PROGRESS, "position": 1},
                {"name": "Work In Progress", "color": "#f59e0b", "category": StatusCategory.IN_PROGRESS, "position": 2},
                {"name": "Pending Approval", "color": "#8b5cf6", "category": StatusCategory.IN_PROGRESS, "position": 3},
                {"name": "Resolved",         "color": "#22c55e", "category": StatusCategory.DONE,        "position": 4},
                {"name": "Closed",           "color": "#6366f1", "category": StatusCategory.DONE,        "position": 5},
                {"name": "Rejected",         "color": "#ef4444", "category": StatusCategory.DONE,        "position": 6},
            ]
            for s in statuses_data:
                db.add(TicketStatus(workflow_id=wf.id, company_id=COMPANY_ID,
                                    created_at=datetime.utcnow(), **s))
            db.flush()

            sm = {s.name: s.id for s in db.query(TicketStatus).filter_by(workflow_id=wf.id).all()}

            transitions_data = [
                # name,                     from,               to,               conditions (metadata)
                ("Accept & Assign",          "Filed",            "Assigned",
                 {"allowed_roles": ["agent", "supervisor", "contractor"],
                  "note": "Field worker accepts the complaint"}),
                ("Start Work",               "Assigned",         "Work In Progress",
                 {"allowed_roles": ["agent", "supervisor", "contractor"]}),
                ("Submit for Review",        "Work In Progress", "Pending Approval",
                 {"allowed_roles": ["agent", "contractor"],
                  "note": "Submit completed work for supervisor review"}),
                ("Approve & Resolve",        "Pending Approval", "Resolved",
                 {"allowed_roles": ["supervisor"],
                  "note": "Supervisor confirms complaint is resolved"}),
                ("Request More Info",        "Pending Approval", "Work In Progress",
                 {"allowed_roles": ["supervisor"],
                  "note": "Supervisor sends back for more work"}),
                ("Close Complaint",          "Resolved",         "Closed",
                 {"allowed_roles": ["supervisor"],
                  "note": "Final closure after resolution confirmed"}),
                ("Reject",                   None,               "Rejected",
                 {"allowed_roles": ["supervisor"],
                  "note": "Supervisor rejects invalid complaint"}),
                ("Reopen",                   "Rejected",         "Filed",
                 {"allowed_roles": ["agent", "supervisor"],
                  "note": "Reconsider a rejected complaint"}),
                ("Reopen from Closed",       "Closed",           "Filed",
                 {"allowed_roles": ["supervisor"],
                  "note": "Reopen a closed complaint if issue recurs"}),
            ]

            for t_name, from_name, to_name, conds in transitions_data:
                db.add(TicketTransition(
                    workflow_id=wf.id,
                    name=t_name,
                    from_status_id=sm.get(from_name) if from_name else None,
                    to_status_id=sm[to_name],
                    conditions=conds,
                    created_at=datetime.utcnow(),
                ))
            db.flush()
            print(f"  created workflow '{wf.name}' id={wf.id} with {len(statuses_data)} statuses, {len(transitions_data)} transitions")

        # ── Ticket Project ─────────────────────────────────────────────────────
        print("\n═══ 5. Ticket Project ═══")
        project = db.query(TicketProject).filter_by(company_id=COMPANY_ID, key="GRV").first()
        if project:
            print(f"  skip project GRV (exists, id={project.id})")
            # Ensure it uses our civic workflow
            if project.default_workflow_id != wf.id:
                project.default_workflow_id = wf.id
                db.flush()
        else:
            project = TicketProject(
                company_id=COMPANY_ID,
                created_by_id=super1.id,
                name="Citizen Grievance Portal",
                key="GRV",
                description="Municipal complaint management system",
                color="#6366f1",
                default_workflow_id=wf.id,
                ticket_counter=0,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            db.add(project)
            db.flush()
            print(f"  created project 'Citizen Grievance Portal' (GRV)  id={project.id}")

        db.commit()

        # ── Routing Rules ──────────────────────────────────────────────────────
        print("\n═══ 6. Routing Rules ═══")
        classif_type  = get_hierarchy_type(db, "Classification")
        location_type = get_hierarchy_type(db, "Location")

        def upsert_rule(name, priority, conditions, action_type, action_config):
            """Create or fully update a routing rule."""
            rule = db.query(RoutingRule).filter_by(company_id=COMPANY_ID, name=name).first()
            if rule:
                rule.priority     = priority
                rule.conditions   = conditions
                rule.action_type  = action_type
                rule.action_config = action_config
                rule.updated_at   = datetime.utcnow()
                db.flush()
                print(f"  updated rule: {name}")
            else:
                rule = RoutingRule(
                    company_id=COMPANY_ID, entity_type="ticket",
                    name=name, priority=priority, trigger="on_create",
                    conditions=conditions, action_type=action_type,
                    action_config=action_config, is_active=True,
                    created_at=datetime.utcnow(), updated_at=datetime.utcnow(),
                )
                db.add(rule)
                db.flush()
                print(f"  created rule: {name}  (priority={priority})")
            return rule

        # Rule 1 — Infrastructure: classification AND location (Maharashtra) → Infra dept
        upsert_rule(
            name="Infrastructure complaints → Infra Dept Agent",
            priority=10,
            conditions=[
                {
                    "field": "custom_fields.classification",
                    "operator": "in",
                    "value": [
                        "infra", "infra_roads", "infra_water", "infra_elec",
                        "infra_roads_pothole", "infra_roads_streetlight", "infra_roads_traffic",
                        "infra_water_pipe", "infra_water_sewage", "infra_water_nosupply",
                        "infra_elec_outage", "infra_elec_transformer",
                    ],
                },
                {
                    "field": "custom_fields.location",
                    "operator": "in",
                    "value": [
                        "in_mh", "in_mh_mum", "in_mh_mum_andheri", "in_mh_mum_bandra",
                        "in_mh_mum_dadar", "in_mh_pune", "in_mh_pune_kothrud",
                        "in_mh_pune_wakad", "in_mh_nagpur",
                    ],
                },
            ],
            action_type="assign_by_department",
            action_config={
                "node_fields": ["classification", "location"],
                "type_map": {
                    "classification": classif_type.id,
                    "location":       location_type.id,
                },
                "role": "agent",
                "ancestor_match": True,
            },
        )

        # Rule 2 — Health & Civic: classification AND location (Karnataka/TN) → Health dept
        upsert_rule(
            name="Health & Civic complaints → Health Dept Agent",
            priority=20,
            conditions=[
                {
                    "field": "custom_fields.classification",
                    "operator": "in",
                    "value": [
                        "health", "health_garbage", "health_mosquito",
                        "health_food", "health_food_restaurant", "health_food_market",
                        "civic", "civic_birth", "civic_death", "civic_propertytax", "civic_buildingpermit",
                        "law", "law_noise", "law_encroach", "law_illegalconstruct",
                    ],
                },
                {
                    "field": "custom_fields.location",
                    "operator": "in",
                    "value": [
                        "in_ka", "in_ka_blr", "in_ka_blr_koramangala",
                        "in_ka_blr_whitefield", "in_ka_mys",
                        "in_tn", "in_tn_che", "in_tn_cbe",
                    ],
                },
            ],
            action_type="assign_by_department",
            action_config={
                "node_fields": ["classification", "location"],
                "type_map": {
                    "classification": classif_type.id,
                    "location":       location_type.id,
                },
                "role": "agent",
                "ancestor_match": True,
            },
        )

        # Rule 3 — Fallback: catch-all → supervisor
        upsert_rule(
            name="Fallback — assign to supervisor",
            priority=99,
            conditions=[],
            action_type="assign_to_user",
            action_config={"user_id": super1.id},
        )

        # Rule 4 — on_transition (scoped): unassigned ticket submitted for review → supervisor
        # Fires on "Submit for Review" transition (id=30) regardless of classification/location
        submit_transition = find_transition(db, wf.id, "Submit for Review")
        upsert_rule(
            name="[on_transition] Unassigned on Submit for Review → Supervisor",
            priority=5,
            conditions=[],
            action_type="assign_to_user",
            action_config={"user_id": super1.id},
        )
        rule4 = db.query(RoutingRule).filter_by(
            company_id=COMPANY_ID,
            name="[on_transition] Unassigned on Submit for Review → Supervisor"
        ).first()
        rule4.trigger = "on_transition"
        rule4.entity_type = "ticket"
        rule4.trigger_transition_id = submit_transition.id
        db.flush()

        # Rule 5 — on_transition (general): unassigned critical/high ticket on Accept & Assign → infra agent
        accept_transition = find_transition(db, wf.id, "Accept & Assign")
        upsert_rule(
            name="[on_transition] Critical/High unassigned on Accept → Infra Agent",
            priority=8,
            conditions=[
                {"field": "priority", "operator": "in", "value": ["critical", "high"]},
            ],
            action_type="assign_to_user",
            action_config={"user_id": agent1.id},
        )
        rule5 = db.query(RoutingRule).filter_by(
            company_id=COMPANY_ID,
            name="[on_transition] Critical/High unassigned on Accept → Infra Agent"
        ).first()
        rule5.trigger = "on_transition"
        rule5.entity_type = "ticket"
        rule5.trigger_transition_id = accept_transition.id
        db.flush()

        db.commit()
        print(f"  on_transition rule 4 (Submit for Review → supervisor, transition_id={submit_transition.id})")
        print(f"  on_transition rule 5 (Accept & Assign + high/critical → Arun, transition_id={accept_transition.id})")

        # ── Test Tickets ───────────────────────────────────────────────────────
        print("\n═══ 7. Test Tickets (filed by citizen Riya) ═══")
        db.refresh(project)

        def get_or_create_ticket(ticket_number, *, classification_code, location_code,
                                 title, desc, priority="medium"):
            from app.models.ticket import Ticket as T
            from sqlalchemy.orm.attributes import flag_modified
            existing = db.query(T).filter_by(
                company_id=COMPANY_ID, ticket_number=ticket_number
            ).first()
            if existing:
                existing.custom_fields = {
                    "classification": classification_code,
                    "location":       location_code,
                }
                flag_modified(existing, "custom_fields")
                db.flush()
                print(f"  updated ticket {ticket_number}  [{classification_code} @ {location_code}]")
                return existing
            return create_ticket(
                db=db, project=project, workflow=wf, reporter=citizen,
                title=title, desc=desc,
                classification_code=classification_code,
                location_code=location_code, priority=priority,
            )

        t1 = get_or_create_ticket("GRV-1",
            title="Pothole on NH48 near Bandra flyover",
            desc="Large pothole causing vehicle damage. Needs immediate repair.",
            classification_code="infra_roads_pothole", location_code="in_mh_mum_bandra", priority="high")

        t2 = get_or_create_ticket("GRV-2",
            title="Sewage overflow in Dadar market area",
            desc="Sewage has been overflowing for 3 days. Health hazard.",
            classification_code="infra_water_sewage", location_code="in_mh_mum_dadar", priority="critical")

        t3 = get_or_create_ticket("GRV-3",
            title="Garbage not collected in Koramangala for 5 days",
            desc="Solid waste piling up. Urgent collection required.",
            classification_code="health_garbage", location_code="in_ka_blr_koramangala", priority="high")

        t4 = get_or_create_ticket("GRV-4",
            title="Birth certificate application stuck for 2 months",
            desc="Applied 2 months ago, no response from civic office.",
            classification_code="civic_birth", location_code="in_ka_blr", priority="medium")

        t5 = get_or_create_ticket("GRV-5",
            title="Noise complaint: construction at night near Whitefield",
            desc="Illegal construction work happening past midnight.",
            classification_code="law_noise", location_code="in_ka_blr_whitefield", priority="medium")

        # GRV-6: intermediate handoff — agent accepts, adds contractor as co-assignee,
        # contractor does the field work, supervisor reviews, agent closes
        t6 = get_or_create_ticket("GRV-6",
            title="Broken streetlight on MG Road causing accidents",
            desc="Three streetlights non-functional. Road dark and dangerous at night.",
            classification_code="infra_roads_streetlight", location_code="in_mh_mum_andheri", priority="high")

        # GRV-7: deliberately unassigned — tests on_transition routing
        # Created directly without going through routing, simulating a ticket that
        # slipped through (e.g., filed before classification was set)
        existing_t7 = db.query(Ticket).filter_by(
            company_id=COMPANY_ID, ticket_number="GRV-7"
        ).first()
        if existing_t7:
            t7 = existing_t7
            print(f"  skip ticket GRV-7 (exists)")
        else:
            t7 = create_ticket(
                db=db, project=project, workflow=wf, reporter=citizen,
                title="Water supply cut for 2 days in Nagpur East",
                desc="Entire locality has no water. No prior notice. Urgent restoration needed.",
                classification_code="infra_water_nosupply",
                location_code="in_mh_nagpur",
                priority="critical",
            )
            # intentionally NOT routed — stays unassigned to test on_transition rules
            print(f"  [GRV-7] created UNASSIGNED — will be routed by on_transition rules")

        db.commit()

        # Apply routing (simulate on_create routing)
        print("\n  Applying routing rules to test tickets…")
        from app.services.routing_service import evaluate_and_route
        for ticket in [t1, t2, t3, t4, t5, t6]:
            db.refresh(ticket)
            assigned_id = evaluate_and_route(db, ticket, "ticket", COMPANY_ID, trigger="on_create")
            if assigned_id:
                ticket.assignee_id = assigned_id
                assignee = db.query(User).filter_by(id=assigned_id).first()
                print(f"    {ticket.ticket_number} → assigned to {assignee.first_name} {assignee.last_name}")
            else:
                print(f"    {ticket.ticket_number} → no routing match")
        db.commit()

        # ── Transitions (only run if ticket is still in initial 'Filed' status) ─
        def ticket_status_name(t):
            s = db.query(TicketStatus).filter_by(id=t.status_id).first()
            return s.name if s else ""

        print("\n═══ 8. Workflow Transitions ═══")

        # GRV-1 full cycle (only if still at Filed)
        db.refresh(t1)
        if ticket_status_name(t1) not in ("Filed",):
            print(f"  [GRV-1] already past Filed — skipping transitions")
        else:
            do_transition(db, t1, wf.id, agent1, "Accept & Assign", "Filed",
                          comment="Taking ownership of this pothole repair.")
            db.commit(); db.refresh(t1)
            do_transition(db, t1, wf.id, agent1, "Start Work", "Assigned",
                          comment="On-site assessment done. Repair crew dispatched.")
            db.commit(); db.refresh(t1)
            do_transition(db, t1, wf.id, agent1, "Submit for Review", "Work In Progress",
                          comment="Repair completed. Please verify and close.")
            db.commit(); db.refresh(t1)
            do_transition(db, t1, wf.id, super1, "Approve & Resolve", "Pending Approval",
                          comment="Site inspected. Work quality confirmed. Marking resolved.")
            db.commit(); db.refresh(t1)
            do_transition(db, t1, wf.id, super1, "Close Complaint", "Resolved",
                          comment="Citizen confirmation received. Closing complaint.")
            db.commit()

        # GRV-2 → contractor accepts, submits, supervisor sends back, contractor resubmits
        db.refresh(t2)
        if ticket_status_name(t2) not in ("Filed",):
            print(f"  [GRV-2] already past Filed — skipping transitions")
        else:
            do_transition(db, t2, wf.id, contract, "Accept & Assign", "Filed",
                          comment="Vikram (contractor) taking this sewage job.")
            db.commit(); db.refresh(t2)
            do_transition(db, t2, wf.id, contract, "Start Work", "Assigned")
            db.commit(); db.refresh(t2)
            do_transition(db, t2, wf.id, contract, "Submit for Review", "Work In Progress",
                          comment="Pipe sealed temporarily. Permanent fix pending.")
            db.commit(); db.refresh(t2)
            do_transition(db, t2, wf.id, super1, "Request More Info", "Pending Approval",
                          comment="Permanent repair needs to be confirmed, not just temporary seal.")
            db.commit(); db.refresh(t2)
            do_transition(db, t2, wf.id, contract, "Submit for Review", "Work In Progress",
                          comment="Permanent pipe replacement done now.")
            db.commit()

        # GRV-3 → agent2 picks up garbage complaint and resolves
        db.refresh(t3)
        if ticket_status_name(t3) not in ("Filed",):
            print(f"  [GRV-3] already past Filed — skipping transitions")
        else:
            do_transition(db, t3, wf.id, agent2, "Accept & Assign", "Filed",
                          comment="Sneha picking up the garbage collection complaint.")
            db.commit(); db.refresh(t3)
            do_transition(db, t3, wf.id, agent2, "Start Work", "Assigned")
            db.commit(); db.refresh(t3)
            do_transition(db, t3, wf.id, agent2, "Submit for Review", "Work In Progress",
                          comment="Collection done. Area cleaned.")
            db.commit()

        # GRV-4 → supervisor rejects, then reopens and agent2 picks up
        db.refresh(t4)
        t4_status = ticket_status_name(t4)
        if t4_status == "Filed":
            do_transition(db, t4, wf.id, super1, "Reject",
                          comment="Birth certificates handled by Revenue Dept, not civic portal.")
            db.commit(); db.refresh(t4)
            do_transition(db, t4, wf.id, super1, "Reopen", "Rejected",
                          comment="Reopening — escalated to civic office.")
            db.commit(); db.refresh(t4)
            do_transition(db, t4, wf.id, agent2, "Accept & Assign", "Filed")
            db.commit()
        else:
            print(f"  [GRV-4] status={t4_status} — skipping transitions")

        # GRV-6: intermediate handoff flow
        #   agent1 accepts → adds contractor as co-assignee → contractor does field work
        #   → supervisor requests changes → contractor resubmits → supervisor approves → agent1 closes
        db.refresh(t6)
        if ticket_status_name(t6) not in ("Filed",):
            print(f"  [GRV-6] already past Filed — skipping transitions")
        else:
            print(f"\n  [GRV-6] Intermediate handoff: agent → contractor → supervisor → agent → close")
            do_transition(db, t6, wf.id, agent1, "Accept & Assign", "Filed",
                          comment="Arun accepting streetlight ticket. Adding Vikram (contractor) as co-assignee for field repair.")
            db.commit(); db.refresh(t6)

            # Add contractor as co-assignee (agent hands off field work)
            from app.services.ticket_service import add_co_assignee
            add_co_assignee(db, ticket_id=t6.id, user_id=contract.id, company_id=COMPANY_ID)
            print(f"    [GRV-6] co-assignee added: {contract.first_name} {contract.last_name}")

            do_transition(db, t6, wf.id, agent1, "Start Work", "Assigned",
                          comment="Dispatching Vikram to inspect all three streetlight points.")
            db.commit(); db.refresh(t6)

            # Contractor does the actual field work and submits
            do_transition(db, t6, wf.id, contract, "Submit for Review", "Work In Progress",
                          comment="All three streetlights replaced. New wiring done. Testing complete.")
            db.commit(); db.refresh(t6)

            # Supervisor sends back — wants photo evidence
            do_transition(db, t6, wf.id, super1, "Request More Info", "Pending Approval",
                          comment="Need before/after photos uploaded as attachments.")
            db.commit(); db.refresh(t6)

            # Contractor resubmits after adding photos
            do_transition(db, t6, wf.id, contract, "Submit for Review", "Work In Progress",
                          comment="Photos uploaded. All lights functional and verified.")
            db.commit(); db.refresh(t6)

            # Supervisor approves
            do_transition(db, t6, wf.id, super1, "Approve & Resolve", "Pending Approval",
                          comment="Photos reviewed. Work quality confirmed. Marking resolved.")
            db.commit(); db.refresh(t6)

            # Original agent closes the ticket
            do_transition(db, t6, wf.id, agent1, "Close Complaint", "Resolved",
                          comment="Citizen notified. All streetlights functional. Closing complaint.")
            db.commit()

        # GRV-7: on_transition routing tests
        # Rule 5 should fire on "Accept & Assign" (critical + unassigned → Arun)
        # Rule 4 should fire on "Submit for Review" (unassigned → supervisor), but
        #   after rule 5 fires and assigns Arun, the ticket is no longer unassigned,
        #   so rule 4 is bypassed — this is the correct behaviour.
        db.refresh(t7)
        print(f"\n  [GRV-7] on_transition routing test (ticket is unassigned, priority=critical)")
        if ticket_status_name(t7) != "Filed":
            print(f"  [GRV-7] status={ticket_status_name(t7)} — skipping on_transition test")
        else:
            print(f"  [GRV-7] assignee before transition: {t7.assignee_id!r}  (should be None)")

            # Transition 1: Accept & Assign (unassigned + critical) → Rule 5 → assigns Arun
            do_transition(db, t7, wf.id, agent1, "Accept & Assign", "Filed",
                          comment="Accepting water supply emergency.")
            db.commit(); db.refresh(t7)
            assignee_after = db.query(User).filter_by(id=t7.assignee_id).first() if t7.assignee_id else None
            name_str = (assignee_after.first_name + ' ' + assignee_after.last_name) if assignee_after else 'STILL UNASSIGNED'
            print(f"  [GRV-7] assignee after Accept & Assign: {name_str}")
            print(f"         → expected: Arun Mehta (via Rule 5 on_transition)")

            do_transition(db, t7, wf.id, agent1, "Start Work", "Assigned",
                          comment="Coordinating with water board for emergency restoration.")
            db.commit(); db.refresh(t7)
            do_transition(db, t7, wf.id, agent1, "Submit for Review", "Work In Progress",
                          comment="Water supply restored in all affected areas.")
            db.commit()

        print("\n═══ Summary ═══")
        print(f"  Users:       riya.sharma (citizen), arun.mehta (agent), priya.nair (supervisor),")
        print(f"               vikram.patel (contractor), sneha.joshi (agent)")
        print(f"  Password:    {DEFAULT_PASS}  (all users)")
        print(f"  Departments: Infrastructure & Public Works | Health & Civic Services")
        print(f"  Project:     Citizen Grievance Portal  (GRV)")
        print(f"  Workflow:    Civic Grievance Workflow  (7 statuses, 9 transitions)")
        print(f"  Rules:       3 routing rules (infra → dept agent, health/civic → dept agent, fallback)")
        print(f"  Tickets:     GRV-1 → Closed, GRV-2 → Pending Approval, GRV-3 → Pending Approval,")
        print(f"               GRV-4 → Assigned (reopened from Rejected), GRV-5 → Filed,")
        print(f"               GRV-6 → Closed (agent→co-assign contractor→supervisor→agent handoff)")
        print(f"               GRV-7 → Pending Approval (on_transition rules tested: Rule5→Arun, Rule4 bypassed)")
        print(f"  Rules:       5 total (3 on_create + 2 on_transition with transition_id scoping)")
        print("\nDone ✓")

    except Exception as e:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
