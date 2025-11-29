import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, get_current_active_user
from app.schemas import template as schemas_template
from app.models import user as models_user
from app.models.template import Template
from app.services.template_ai_service import template_ai_service
from app.services import credential_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/providers", response_model=schemas_template.AIProvidersResponse)
async def get_ai_providers(
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Get list of supported AI providers and their models.
    """
    providers = template_ai_service.get_available_providers()
    return schemas_template.AIProvidersResponse(providers=providers)


@router.post("/generate", response_model=schemas_template.AIGenerateResponse)
async def generate_template(
    request: schemas_template.AIGenerateRequest,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Generate a template using AI based on the provided prompt and parameters.
    Requires a valid vault credential for the LLM provider.
    """
    # Verify credential belongs to company
    credential = credential_service.get_credential(db, request.credential_id, current_user.company_id)
    if not credential:
        raise HTTPException(status_code=404, detail="Credential not found")

    try:
        result = await template_ai_service.generate_template(
            db=db,
            company_id=current_user.company_id,
            credential_id=request.credential_id,
            template_type=request.template_type,
            prompt=request.prompt,
            tone=request.tone,
            target_audience=request.target_audience,
            campaign_goal=request.campaign_goal,
            include_cta=request.include_cta,
            language=request.language,
            model=request.model
        )

        return schemas_template.AIGenerateResponse(
            subject=result.get("subject"),
            body=result.get("body", ""),
            html_body=result.get("html_body"),
            personalization_tokens=result.get("personalization_tokens", []),
            suggestions=result.get("suggestions")
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception(f"Error generating template: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/suggest-subjects", response_model=schemas_template.AISuggestSubjectsResponse)
async def suggest_subjects(
    request: schemas_template.AISuggestSubjectsRequest,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Generate subject line suggestions based on email body content.
    """
    # Verify credential belongs to company
    credential = credential_service.get_credential(db, request.credential_id, current_user.company_id)
    if not credential:
        raise HTTPException(status_code=404, detail="Credential not found")

    try:
        subjects = await template_ai_service.generate_subject_lines(
            db=db,
            company_id=current_user.company_id,
            credential_id=request.credential_id,
            body=request.body,
            count=request.count,
            tone=request.tone,
            model=request.model
        )

        return schemas_template.AISuggestSubjectsResponse(subjects=subjects)

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception(f"Error suggesting subjects: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/improve", response_model=schemas_template.AIImproveResponse)
async def improve_content(
    request: schemas_template.AIImproveRequest,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Improve existing template content based on specified criteria.
    """
    # Verify credential belongs to company
    credential = credential_service.get_credential(db, request.credential_id, current_user.company_id)
    if not credential:
        raise HTTPException(status_code=404, detail="Credential not found")

    try:
        result = await template_ai_service.improve_content(
            db=db,
            company_id=current_user.company_id,
            credential_id=request.credential_id,
            content=request.content,
            content_type=request.content_type,
            improvements=request.improvements,
            model=request.model
        )

        return schemas_template.AIImproveResponse(
            improved_content=result.get("improved_content", ""),
            changes_made=result.get("changes_made", [])
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception(f"Error improving content: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/variants", response_model=schemas_template.AIVariantsResponse)
async def generate_variants(
    request: schemas_template.AIVariantsRequest,
    db: Session = Depends(get_db),
    current_user: models_user.User = Depends(get_current_active_user)
):
    """
    Generate A/B test variants for an existing template.
    """
    # Verify credential belongs to company
    credential = credential_service.get_credential(db, request.credential_id, current_user.company_id)
    if not credential:
        raise HTTPException(status_code=404, detail="Credential not found")

    # Fetch the original template
    template = db.query(Template).filter(
        Template.id == request.template_id,
        Template.company_id == current_user.company_id
    ).first()

    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    try:
        variants = await template_ai_service.generate_ab_variants(
            db=db,
            company_id=current_user.company_id,
            credential_id=request.credential_id,
            original_subject=template.subject,
            original_body=template.body or "",
            variant_count=request.variant_count,
            variation_type=request.variation_type,
            model=request.model
        )

        return schemas_template.AIVariantsResponse(variants=variants)

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception(f"Error generating variants: {e}")
        raise HTTPException(status_code=500, detail=str(e))
