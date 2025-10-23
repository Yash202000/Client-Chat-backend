
from fastapi import APIRouter, Depends, HTTPException, Response, File, UploadFile
from sqlalchemy.orm import Session, joinedload
from typing import List, Dict
import json

from app.schemas import ai_tool as ai_tool_schema
from app.crud import crud_ai_tool
from app.core.dependencies import get_db, get_current_active_user, require_permission
from app.models import user as user_model, ai_tool_category as ai_tool_category_model
from app.models import ai_tool as ai_tool_model
from app.services import ai_tool_service

router = APIRouter()

@router.post("/admin/import", tags=["AI Tools"], dependencies=[Depends(require_permission("ai-tool:import"))])
async def import_ai_tools(file: UploadFile = File(...), db: Session = Depends(get_db)):
    content = await file.read()
    tools_data = json.loads(content)

    for tool_data in tools_data:
        # Check if tool with the same name already exists
        existing_tool = db.query(ai_tool_model.AITool).filter(ai_tool_model.AITool.name == tool_data["name"]).first()
        if existing_tool:
            continue

        category_data = tool_data.get("category")
        category_name = category_data.get("name")
        category_icon = category_data.get("icon")

        # Check if category exists, if not create it
        category = db.query(ai_tool_category_model.AIToolCategory).filter(ai_tool_category_model.AIToolCategory.name == category_name).first()
        if not category:
            category = crud_ai_tool.create_ai_tool_category(db, ai_tool_schema.AIToolCategoryCreate(name=category_name, icon=category_icon))

        # Create the AI tool
        tool_create = ai_tool_schema.AIToolCreate(
            name=tool_data["name"],
            description=tool_data["description"],
            category_id=category.id,
            questions=[ai_tool_schema.AIToolQuestionCreate(**q) for q in tool_data["questions"]]
        )
        crud_ai_tool.create_ai_tool(db, tool_create)

    return {"message": "AI tools imported successfully"}


@router.get("/admin/export", tags=["AI Tools"], dependencies=[Depends(require_permission("ai-tool:export"))])
def export_ai_tools(db: Session = Depends(get_db)):
    tools = db.query(ai_tool_model.AITool).options(joinedload(ai_tool_model.AITool.category), joinedload(ai_tool_model.AITool.questions)).all()
    
    # Manually construct the dictionary to ensure all required fields are included
    tools_data = []
    for tool in tools:
        tool_data = {
            "name": tool.name,
            "description": tool.description,
            "category": {
                "name": tool.category.name,
                "icon": tool.category.icon
            },
            "questions": [
                {
                    "question_text": q.question_text,
                    "question_type": q.question_type,
                    "hint": q.hint
                } for q in tool.questions
            ]
        }
        tools_data.append(tool_data)

    return Response(
        content=json.dumps(tools_data, indent=4),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=ai_tools.json"}
    )


@router.post("/categories/", response_model=ai_tool_schema.AIToolCategory, tags=["AI Tools"], dependencies=[Depends(require_permission("ai-tool-category:create"))])
def create_ai_tool_category(category: ai_tool_schema.AIToolCategoryCreate, db: Session = Depends(get_db)):
    return crud_ai_tool.create_ai_tool_category(db=db, category=category)

@router.get("/categories/", response_model=List[ai_tool_schema.AIToolCategory], tags=["AI Tools"], dependencies=[Depends(require_permission("ai-tool-category:read"))])
def read_ai_tool_categories(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    categories = crud_ai_tool.get_ai_tool_categories(db, skip=skip, limit=limit)
    return categories

@router.get("/categories/{category_id}", response_model=ai_tool_schema.AIToolCategory, tags=["AI Tools"], dependencies=[Depends(require_permission("ai-tool-category:read"))])
def read_ai_tool_category(category_id: int, db: Session = Depends(get_db)):
    db_category = crud_ai_tool.get_ai_tool_category(db, category_id=category_id)
    if db_category is None:
        raise HTTPException(status_code=404, detail="Category not found")
    return db_category

@router.post("/", response_model=ai_tool_schema.AITool, tags=["AI Tools"], dependencies=[Depends(require_permission("ai-tool:create"))])
def create_ai_tool(tool: ai_tool_schema.AIToolCreate, db: Session = Depends(get_db)):
    return crud_ai_tool.create_ai_tool(db=db, tool=tool)

@router.get("/", response_model=List[ai_tool_schema.AITool], tags=["AI Tools"], dependencies=[Depends(require_permission("ai-tool:read"))])
def read_ai_tools(skip: int = 0, limit: int = 100, db: Session = Depends(get_db), current_user: user_model.User = Depends(get_current_active_user)):
    tools = crud_ai_tool.get_ai_tools(db, skip=skip, limit=limit, user_id=current_user.id)
    return tools

@router.get("/{tool_id}", response_model=ai_tool_schema.AITool, tags=["AI Tools"], dependencies=[Depends(require_permission("ai-tool:read"))])
def read_ai_tool(tool_id: int, db: Session = Depends(get_db), current_user: user_model.User = Depends(get_current_active_user)):
    db_tool = crud_ai_tool.get_ai_tool(db, tool_id=tool_id, user_id=current_user.id)
    if db_tool is None:
        raise HTTPException(status_code=404, detail="Tool not found")
    return db_tool

@router.put("/{tool_id}", response_model=ai_tool_schema.AITool, tags=["AI Tools"], dependencies=[Depends(require_permission("ai-tool:update"))])
def update_ai_tool(tool_id: int, tool: ai_tool_schema.AIToolCreate, db: Session = Depends(get_db)):
    return crud_ai_tool.update_ai_tool(db=db, tool_id=tool_id, tool=tool)

@router.delete("/{tool_id}", tags=["AI Tools"], dependencies=[Depends(require_permission("ai-tool:delete"))])
def delete_ai_tool(tool_id: int, db: Session = Depends(get_db)):
    crud_ai_tool.delete_ai_tool(db=db, tool_id=tool_id)
    return {"message": "Tool deleted successfully"}

@router.delete("/questions/{question_id}", tags=["AI Tools"], dependencies=[Depends(require_permission("ai-tool:update"))])
def delete_ai_tool_question(question_id: int, db: Session = Depends(get_db)):
    crud_ai_tool.delete_ai_tool_question(db=db, question_id=question_id)
    return {"message": "Question deleted successfully"}

@router.post("/{tool_id}/favorite", tags=["AI Tools"])
def favorite_tool(tool_id: int, db: Session = Depends(get_db), current_user: user_model.User = Depends(get_current_active_user)):
    db_tool = crud_ai_tool.get_ai_tool(db, tool_id=tool_id)
    if db_tool is None:
        raise HTTPException(status_code=404, detail="Tool not found")
    db.execute(ai_tool_model.ai_tool_favorites.insert().values(user_id=current_user.id, ai_tool_id=tool_id))
    db.commit()
    return {"message": "Tool favorited successfully"}

@router.delete("/{tool_id}/favorite", tags=["AI Tools"])
def unfavorite_tool(tool_id: int, db: Session = Depends(get_db), current_user: user_model.User = Depends(get_current_active_user)):
    db_tool = crud_ai_tool.get_ai_tool(db, tool_id=tool_id)
    if db_tool is None:
        raise HTTPException(status_code=404, detail="Tool not found")
    db.execute(ai_tool_model.ai_tool_favorites.delete().where(
        ai_tool_model.ai_tool_favorites.c.user_id == current_user.id,
        ai_tool_model.ai_tool_favorites.c.ai_tool_id == tool_id
    ))
    db.commit()
    return {"message": "Tool unfavorited successfully"}


@router.post("/{tool_id}/execute", tags=["AI Tools"], dependencies=[Depends(require_permission("ai-tool:read"))])
def execute_tool(tool_id: int, request: ai_tool_schema.ExecuteToolRequest, db: Session = Depends(get_db), current_user: user_model.User = Depends(get_current_active_user)):
    print(f"Received answers: {request.answers}")
    print(f"Received language: {request.language}")
    db_tool = crud_ai_tool.get_ai_tool(db, tool_id=tool_id)
    if db_tool is None:
        raise HTTPException(status_code=404, detail="Tool not found")
    result = ai_tool_service.execute_ai_tool(db, current_user, db_tool, request.answers, request.language)
    return {"result": result}
