from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.core.dependencies import get_db, get_current_active_user, require_permission
from app.services import pipeline_service
from app.schemas import pipeline as schemas_pipeline
from app.models import user as models_user

router = APIRouter()


@router.get("/", response_model=List[schemas_pipeline.Pipeline], dependencies=[Depends(require_permission("pipeline:read"))])
def list_pipelines(
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    return pipeline_service.get_pipelines(db=db, company_id=current_user.company_id)


@router.post("/", response_model=schemas_pipeline.Pipeline, dependencies=[Depends(require_permission("pipeline:create"))])
def create_pipeline(
    pipeline: schemas_pipeline.PipelineCreate,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    return pipeline_service.create_pipeline(db=db, pipeline=pipeline, company_id=current_user.company_id)


@router.get("/{pipeline_id}", response_model=schemas_pipeline.Pipeline, dependencies=[Depends(require_permission("pipeline:read"))])
def get_pipeline(
    pipeline_id: int,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    pl = pipeline_service.get_pipeline(db=db, pipeline_id=pipeline_id, company_id=current_user.company_id)
    if not pl:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    return pl


@router.put("/{pipeline_id}", response_model=schemas_pipeline.Pipeline, dependencies=[Depends(require_permission("pipeline:update"))])
def update_pipeline(
    pipeline_id: int,
    pipeline: schemas_pipeline.PipelineUpdate,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    updated = pipeline_service.update_pipeline(db=db, pipeline_id=pipeline_id, pipeline=pipeline, company_id=current_user.company_id)
    if not updated:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    return updated


@router.delete("/{pipeline_id}", dependencies=[Depends(require_permission("pipeline:delete"))])
def delete_pipeline(
    pipeline_id: int,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    deleted = pipeline_service.delete_pipeline(db=db, pipeline_id=pipeline_id, company_id=current_user.company_id)
    if not deleted:
        raise HTTPException(status_code=400, detail="Cannot delete default pipeline or pipeline not found")
    return {"ok": True}


# Stage sub-routes
@router.post("/{pipeline_id}/stages", response_model=schemas_pipeline.DealStage, dependencies=[Depends(require_permission("pipeline:update"))])
def create_stage(
    pipeline_id: int,
    stage: schemas_pipeline.DealStageCreate,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    pl = pipeline_service.get_pipeline(db=db, pipeline_id=pipeline_id, company_id=current_user.company_id)
    if not pl:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    return pipeline_service.create_stage(db=db, pipeline_id=pipeline_id, stage=stage)


@router.put("/{pipeline_id}/stages/{stage_id}", response_model=schemas_pipeline.DealStage, dependencies=[Depends(require_permission("pipeline:update"))])
def update_stage(
    pipeline_id: int,
    stage_id: int,
    stage: schemas_pipeline.DealStageUpdate,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    updated = pipeline_service.update_stage(db=db, stage_id=stage_id, pipeline_id=pipeline_id, stage=stage)
    if not updated:
        raise HTTPException(status_code=404, detail="Stage not found")
    return updated


@router.delete("/{pipeline_id}/stages/{stage_id}", dependencies=[Depends(require_permission("pipeline:update"))])
def delete_stage(
    pipeline_id: int,
    stage_id: int,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    deleted = pipeline_service.delete_stage(db=db, stage_id=stage_id, pipeline_id=pipeline_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Stage not found")
    return {"ok": True}
