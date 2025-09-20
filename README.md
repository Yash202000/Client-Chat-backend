# Client-Chat-backend
# Client-Chat-backend


source venv/bin/activate

uvicorn app.main:app --reload


# Generate migration when models change:

alembic revision --autogenerate -m "initial schema"


alembic revision --autogenerate -m "Add multitenancy unique constraint"


# Apply migration:

alembic upgrade head

# for clint

npm install 

npm run dev


# for fastmcp 

# Run MCP server
# pip install fastmcp pydantic google-api-python-client google-auth-httplib2 google-auth-oauthlib
# fastmcp run main.py --transport http --port 8100



