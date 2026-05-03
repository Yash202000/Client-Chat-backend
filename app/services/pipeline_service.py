from sqlalchemy.orm import Session
from typing import List, Optional
from app.models.pipeline import Pipeline, DealStage
from app.schemas.pipeline import PipelineCreate, PipelineUpdate, DealStageCreate, DealStageUpdate

DEFAULT_STAGES = [
    {"name": "New", "position": 0, "probability": 10, "color": "#6366f1"},
    {"name": "Qualified", "position": 1, "probability": 25, "color": "#3b82f6"},
    {"name": "Proposal", "position": 2, "probability": 50, "color": "#f59e0b"},
    {"name": "Negotiation", "position": 3, "probability": 75, "color": "#f97316"},
    {"name": "Closed Won", "position": 4, "probability": 100, "color": "#22c55e"},
    {"name": "Closed Lost", "position": 5, "probability": 0, "color": "#ef4444"},
]


def get_pipeline(db: Session, pipeline_id: int, company_id: int) -> Optional[Pipeline]:
    return db.query(Pipeline).filter(
        Pipeline.id == pipeline_id, Pipeline.company_id == company_id
    ).first()


def get_pipelines(db: Session, company_id: int) -> List[Pipeline]:
    return db.query(Pipeline).filter(Pipeline.company_id == company_id).all()


def create_pipeline(db: Session, pipeline: PipelineCreate, company_id: int) -> Pipeline:
    # Only one default pipeline per company
    if pipeline.is_default:
        db.query(Pipeline).filter(
            Pipeline.company_id == company_id, Pipeline.is_default == True
        ).update({"is_default": False})

    db_pipeline = Pipeline(name=pipeline.name, is_default=pipeline.is_default, company_id=company_id)
    db.add(db_pipeline)
    db.flush()

    stage_defs = pipeline.stages if pipeline.stages else [DealStageCreate(**s) for s in DEFAULT_STAGES]
    for s in stage_defs:
        db.add(DealStage(pipeline_id=db_pipeline.id, **s.model_dump()))

    db.commit()
    db.refresh(db_pipeline)
    return db_pipeline


def ensure_default_pipeline(db: Session, company_id: int) -> Pipeline:
    existing = db.query(Pipeline).filter(
        Pipeline.company_id == company_id, Pipeline.is_default == True
    ).first()
    if existing:
        return existing
    return create_pipeline(db, PipelineCreate(name="Sales Pipeline", is_default=True), company_id)


def update_pipeline(db: Session, pipeline_id: int, pipeline: PipelineUpdate, company_id: int) -> Optional[Pipeline]:
    db_pipeline = get_pipeline(db, pipeline_id, company_id)
    if not db_pipeline:
        return None
    if pipeline.is_default:
        db.query(Pipeline).filter(
            Pipeline.company_id == company_id, Pipeline.is_default == True
        ).update({"is_default": False})
    for key, value in pipeline.model_dump(exclude_unset=True).items():
        setattr(db_pipeline, key, value)
    db.commit()
    db.refresh(db_pipeline)
    return db_pipeline


def delete_pipeline(db: Session, pipeline_id: int, company_id: int) -> bool:
    db_pipeline = get_pipeline(db, pipeline_id, company_id)
    if not db_pipeline or db_pipeline.is_default:
        return False
    db.delete(db_pipeline)
    db.commit()
    return True


def get_stage(db: Session, stage_id: int, pipeline_id: int) -> Optional[DealStage]:
    return db.query(DealStage).filter(
        DealStage.id == stage_id, DealStage.pipeline_id == pipeline_id
    ).first()


def create_stage(db: Session, pipeline_id: int, stage: DealStageCreate) -> DealStage:
    db_stage = DealStage(pipeline_id=pipeline_id, **stage.model_dump())
    db.add(db_stage)
    db.commit()
    db.refresh(db_stage)
    return db_stage


def update_stage(db: Session, stage_id: int, pipeline_id: int, stage: DealStageUpdate) -> Optional[DealStage]:
    db_stage = get_stage(db, stage_id, pipeline_id)
    if not db_stage:
        return None
    for key, value in stage.model_dump(exclude_unset=True).items():
        setattr(db_stage, key, value)
    db.commit()
    db.refresh(db_stage)
    return db_stage


def delete_stage(db: Session, stage_id: int, pipeline_id: int) -> bool:
    db_stage = get_stage(db, stage_id, pipeline_id)
    if not db_stage:
        return False
    db.delete(db_stage)
    db.commit()
    return True
