
from sqlalchemy.orm import Session
from app.models import ai_tool as ai_tool_model, ai_tool_category as ai_tool_category_model, ai_tool_question as ai_tool_question_model
from app.schemas import ai_tool as ai_tool_schema

# CRUD for AIToolCategory
def create_ai_tool_category(db: Session, category: ai_tool_schema.AIToolCategoryCreate) -> ai_tool_category_model.AIToolCategory:
    db_category = ai_tool_category_model.AIToolCategory(name=category.name, icon=category.icon)
    db.add(db_category)
    db.commit()
    db.refresh(db_category)
    return db_category

def get_ai_tool_category(db: Session, category_id: int) -> ai_tool_category_model.AIToolCategory:
    return db.query(ai_tool_category_model.AIToolCategory).filter(ai_tool_category_model.AIToolCategory.id == category_id).first()

def get_ai_tool_categories(db: Session, skip: int = 0, limit: int = 100):
    return db.query(ai_tool_category_model.AIToolCategory).offset(skip).limit(limit).all()

# CRUD for AITool

def create_ai_tool(db: Session, tool: ai_tool_schema.AIToolCreate) -> ai_tool_model.AITool:
    db_tool = ai_tool_model.AITool(name=tool.name, description=tool.description, category_id=tool.category_id)
    for question in tool.questions:
        db_tool.questions.append(ai_tool_question_model.AIToolQuestion(**question.model_dump()))
    db.add(db_tool)
    db.commit()
    db.refresh(db_tool)
    return db_tool

def get_ai_tool(db: Session, tool_id: int, user_id: int = None) -> ai_tool_model.AITool:
    tool = db.query(ai_tool_model.AITool).filter(ai_tool_model.AITool.id == tool_id).first()
    if tool and user_id:
        tool.is_favorited = db.query(ai_tool_model.ai_tool_favorites).filter(
            ai_tool_model.ai_tool_favorites.c.user_id == user_id,
            ai_tool_model.ai_tool_favorites.c.ai_tool_id == tool.id
        ).first() is not None
    return tool

def get_ai_tools(db: Session, skip: int = 0, limit: int = 100, user_id: int = None):
    tools = db.query(ai_tool_model.AITool).offset(skip).limit(limit).all()
    if user_id:
        for tool in tools:
            tool.is_favorited = db.query(ai_tool_model.ai_tool_favorites).filter(
                ai_tool_model.ai_tool_favorites.c.user_id == user_id,
                ai_tool_model.ai_tool_favorites.c.ai_tool_id == tool.id
            ).first() is not None
    return tools

def update_ai_tool(db: Session, tool_id: int, tool: ai_tool_schema.AIToolCreate) -> ai_tool_model.AITool:
    db_tool = get_ai_tool(db, tool_id)
    if db_tool:
        db_tool.name = tool.name
        db_tool.description = tool.description
        db_tool.category_id = tool.category_id
        # Simple update for questions: delete all and create new ones
        for question in db_tool.questions:
            db.delete(question)
        for question in tool.questions:
            db_tool.questions.append(ai_tool_question_model.AIToolQuestion(**question.model_dump()))
        db.commit()
        db.refresh(db_tool)
    return db_tool


def delete_ai_tool(db: Session, tool_id: int):
    db_tool = get_ai_tool(db, tool_id)
    if db_tool:
        db.delete(db_tool)
        db.commit()
    return db_tool

def delete_ai_tool_question(db: Session, question_id: int):
    db_question = db.query(ai_tool_question_model.AIToolQuestion).filter(ai_tool_question_model.AIToolQuestion.id == question_id).first()
    if db_question:
        db.delete(db_question)
        db.commit()
    return db_question
