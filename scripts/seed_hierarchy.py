"""
Seed test hierarchy data: Location, Classification, Department.
Run from backend/ with:  python scripts/seed_hierarchy.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal
from app.services import hierarchy_service as svc

COMPANY_ID = 1

# ── Tree definitions ──────────────────────────────────────────────────────────

LOCATION_TREE = {
    "type": {"name": "Location", "description": "Geographic jurisdiction tree"},
    "roots": [
        {
            "name": "India", "code": "in",
            "children": [
                {
                    "name": "Maharashtra", "code": "in_mh",
                    "children": [
                        {
                            "name": "Mumbai", "code": "in_mh_mum",
                            "children": [
                                {"name": "Andheri", "code": "in_mh_mum_andheri"},
                                {"name": "Bandra", "code": "in_mh_mum_bandra"},
                                {"name": "Dadar", "code": "in_mh_mum_dadar"},
                            ],
                        },
                        {
                            "name": "Pune", "code": "in_mh_pune",
                            "children": [
                                {"name": "Kothrud", "code": "in_mh_pune_kothrud"},
                                {"name": "Wakad", "code": "in_mh_pune_wakad"},
                            ],
                        },
                        {"name": "Nagpur", "code": "in_mh_nagpur"},
                    ],
                },
                {
                    "name": "Karnataka", "code": "in_ka",
                    "children": [
                        {
                            "name": "Bengaluru", "code": "in_ka_blr",
                            "children": [
                                {"name": "Koramangala", "code": "in_ka_blr_koramangala"},
                                {"name": "Whitefield", "code": "in_ka_blr_whitefield"},
                            ],
                        },
                        {"name": "Mysuru", "code": "in_ka_mys"},
                    ],
                },
                {
                    "name": "Tamil Nadu", "code": "in_tn",
                    "children": [
                        {"name": "Chennai", "code": "in_tn_che"},
                        {"name": "Coimbatore", "code": "in_tn_cbe"},
                    ],
                },
            ],
        }
    ],
}

CLASSIFICATION_TREE = {
    "type": {"name": "Classification", "description": "Complaint / ticket classification taxonomy"},
    "roots": [
        {
            "name": "Infrastructure", "code": "infra",
            "children": [
                {
                    "name": "Roads & Transport", "code": "infra_roads",
                    "children": [
                        {"name": "Pothole", "code": "infra_roads_pothole"},
                        {"name": "Street Light", "code": "infra_roads_streetlight"},
                        {"name": "Traffic Signal", "code": "infra_roads_traffic"},
                    ],
                },
                {
                    "name": "Water & Sewage", "code": "infra_water",
                    "children": [
                        {"name": "Pipe Burst", "code": "infra_water_pipe"},
                        {"name": "Sewage Overflow", "code": "infra_water_sewage"},
                        {"name": "No Water Supply", "code": "infra_water_nosupply"},
                    ],
                },
                {
                    "name": "Electricity", "code": "infra_elec",
                    "children": [
                        {"name": "Power Outage", "code": "infra_elec_outage"},
                        {"name": "Transformer Fault", "code": "infra_elec_transformer"},
                    ],
                },
            ],
        },
        {
            "name": "Public Health", "code": "health",
            "children": [
                {"name": "Garbage Collection", "code": "health_garbage"},
                {"name": "Mosquito Breeding", "code": "health_mosquito"},
                {
                    "name": "Food Safety", "code": "health_food",
                    "children": [
                        {"name": "Restaurant Hygiene", "code": "health_food_restaurant"},
                        {"name": "Market Sanitation", "code": "health_food_market"},
                    ],
                },
            ],
        },
        {
            "name": "Civic Services", "code": "civic",
            "children": [
                {"name": "Birth Certificate", "code": "civic_birth"},
                {"name": "Death Certificate", "code": "civic_death"},
                {"name": "Property Tax", "code": "civic_propertytax"},
                {"name": "Building Permit", "code": "civic_buildingpermit"},
            ],
        },
        {
            "name": "Law & Order", "code": "law",
            "children": [
                {"name": "Noise Complaint", "code": "law_noise"},
                {"name": "Encroachment", "code": "law_encroach"},
                {"name": "Illegal Construction", "code": "law_illegalconstruct"},
            ],
        },
    ],
}

DEPARTMENT_TREE = {
    "type": {"name": "Department", "description": "Organisational department structure"},
    "roots": [
        {
            "name": "Engineering", "code": "eng",
            "children": [
                {
                    "name": "Roads Department", "code": "eng_roads",
                    "children": [
                        {"name": "Roads North Zone", "code": "eng_roads_north"},
                        {"name": "Roads South Zone", "code": "eng_roads_south"},
                    ],
                },
                {
                    "name": "Water & Sanitation", "code": "eng_water",
                    "children": [
                        {"name": "Water Supply", "code": "eng_water_supply"},
                        {"name": "Sewage Treatment", "code": "eng_water_sewage"},
                    ],
                },
                {"name": "Electrical", "code": "eng_elec"},
            ],
        },
        {
            "name": "Health Department", "code": "health_dept",
            "children": [
                {"name": "Solid Waste Management", "code": "health_dept_swm"},
                {"name": "Epidemiology", "code": "health_dept_epi"},
                {"name": "Food Inspection", "code": "health_dept_food"},
            ],
        },
        {
            "name": "Revenue & Finance", "code": "finance",
            "children": [
                {"name": "Property Tax", "code": "finance_tax"},
                {"name": "Accounts", "code": "finance_accounts"},
            ],
        },
        {
            "name": "Town Planning", "code": "planning",
            "children": [
                {"name": "Building Permits", "code": "planning_permits"},
                {"name": "Land Records", "code": "planning_land"},
            ],
        },
        {"name": "Legal & Compliance", "code": "legal"},
        {"name": "IT & Digital Services", "code": "it"},
        {"name": "Human Resources", "code": "hr"},
    ],
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def seed_nodes(db, company_id: int, type_id: int, nodes: list, parent_id=None):
    for item in nodes:
        existing = db.query(__import__('app.models.hierarchy', fromlist=['HierarchyNode']).HierarchyNode).filter_by(
            company_id=company_id, type_id=type_id, code=item["code"]
        ).first()
        if existing:
            node = existing
            print(f"  skip (exists): {item['code']}")
        else:
            node = svc.create_node(db, company_id, type_id, item["name"], item["code"], parent_id)
            print(f"  created: {item['code']} (id={node.id})")
        for child in item.get("children", []):
            seed_nodes(db, company_id, type_id, [child], parent_id=node.id)


def seed_tree(db, company_id: int, tree_def: dict):
    existing_type = db.query(__import__('app.models.hierarchy', fromlist=['HierarchyType']).HierarchyType).filter_by(
        company_id=company_id, name=tree_def["type"]["name"]
    ).first()
    if existing_type:
        ht = existing_type
        print(f"\n[{ht.name}] type already exists (id={ht.id}), seeding nodes...")
    else:
        ht = svc.create_type(db, company_id, tree_def["type"]["name"], tree_def["type"].get("description"))
        print(f"\n[{ht.name}] created type (id={ht.id})")
    seed_nodes(db, company_id, ht.id, tree_def["roots"])


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    db = SessionLocal()
    try:
        for tree in [LOCATION_TREE, CLASSIFICATION_TREE, DEPARTMENT_TREE]:
            seed_tree(db, COMPANY_ID, tree)
        print("\nDone.")
    finally:
        db.close()
