
import pytest
from unittest.mock import Mock, MagicMock
from sqlalchemy.orm import Session
from app.services.workflow_execution_service import WorkflowExecutionService
from app.models.workflow import Workflow
from app.models.agent import Agent
from app.schemas.conversation_session import ConversationSessionUpdate

@pytest.fixture
def mock_db_session():
    return Mock(spec=Session)

@pytest.fixture
def mock_llm_tool_service():
    mock_service = Mock()
    mock_service.execute_llm_call.return_value = "Mocked LLM Response"
    return mock_service

@pytest.fixture
def mock_conversation_session_service():
    mock_service = Mock()
    mock_session = Mock()
    mock_session.context = {}
    mock_session.status = 'completed'
    mock_session.next_step_id = None
    mock_service.get_or_create_session.return_value = mock_session
    mock_service.get_or_create_session.side_effect = lambda db, conversation_id, workflow_id, contact_id, channel, company_id: mock_session
    mock_service.update_session.return_value = None
    return mock_service

@pytest.fixture
def workflow_execution_service(mock_db_session, mock_llm_tool_service, mock_conversation_session_service):
    service = WorkflowExecutionService(mock_db_session)
    service.llm_tool_service = mock_llm_tool_service
    service.conversation_session_service = mock_conversation_session_service # Inject mock
    return service

def test_execute_simple_llm_workflow(workflow_execution_service, mock_db_session):
    # Define a simple workflow with a start, LLM, and output node
    dummy_workflow = Mock(spec=Workflow)
    dummy_workflow.id = 1
    dummy_workflow.agent = Mock(spec=Agent)
    dummy_workflow.agent.company_id = 123
    dummy_workflow.visual_steps = {
        "nodes": [
            {"id": "start_node", "type": "start", "data": {"label": "Start"}},
            {"id": "llm_node", "type": "llm", "data": {"label": "LLM Call", "prompt": "Hello, LLM!"}},
            {"id": "output_node", "type": "output", "data": {"label": "Output"}},
        ],
        "edges": [
            {"id": "e1", "source": "start_node", "target": "llm_node", "sourceHandle": "output"},
            {"id": "e2", "source": "llm_node", "target": "output_node", "sourceHandle": "output"},
        ]
    }

    user_message = "Test message"
    conversation_id = "test_conv_123"

    # Execute the workflow
    result = workflow_execution_service.execute_workflow(dummy_workflow, user_message, conversation_id)

    # Assertions
    assert result["status"] == "completed"
    assert result["response"] == "Mocked LLM Response"
    assert result["conversation_id"] == conversation_id

    # Verify LLM service was called
    workflow_execution_service.llm_tool_service.execute_llm_call.assert_called_once_with("Hello, LLM!")

    # Verify session was updated
    workflow_execution_service.conversation_session_service.update_session.assert_called_once()
    args, kwargs = workflow_execution_service.conversation_session_service.update_session.call_args
    assert args[0] == mock_db_session
    assert args[1] == conversation_id
    assert isinstance(args[2], ConversationSessionUpdate)
    assert args[2].status == 'completed'
