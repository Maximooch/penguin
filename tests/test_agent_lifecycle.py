import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from penguin.agent import PenguinAgent, PenguinAgentAsync, BasicPenguinAgent
from penguin.agent.base import BaseAgent
from penguin.agent.schema import AgentConfig, SecurityConfig
from penguin.agent.launcher import AgentLauncher

@pytest.fixture
def mock_core():
    """Fixture to mock PenguinCore and its components, especially the engine."""
    core = AsyncMock()
    core.engine = AsyncMock()
    core.engine.run_single_turn = AsyncMock(return_value={"assistant_response": "Test response"})
    core.engine.run_task = AsyncMock(return_value={"assistant_response": "Task completed", "status": "completed"})
    core.engine.stream = AsyncMock()
    
    # Mock other core components
    core.conversation_manager = AsyncMock()
    core.api_client = AsyncMock()
    core.tool_manager = AsyncMock()
    core.action_executor = AsyncMock()
    core.project_manager = AsyncMock()
    
    return core

@pytest.fixture
def basic_agent_config():
    """Fixture for basic agent configuration."""
    return AgentConfig(
        name="test_agent",
        type="penguin.agent.basic_agent.BasicPenguinAgent",
        description="Test agent for unit tests",
        security=SecurityConfig()
    )

@pytest.fixture 
def mock_agent_components():
    """Fixture for agent components."""
    components = {
        'conversation_manager': AsyncMock(),
        'api_client': AsyncMock(),
        'tool_manager': AsyncMock(),
        'action_executor': AsyncMock()
    }
    components['conversation_manager'].process_message = AsyncMock(return_value={
        "assistant_response": "Mock response",
        "action_results": []
    })
    return components

class TestPenguinAgent:
    """Test the sync PenguinAgent wrapper."""
    
    @patch('penguin.agent.PenguinCore')
    def test_agent_initialization(self, mock_core_class):
        """Test that PenguinAgent initializes correctly."""
        mock_core_instance = AsyncMock()
        mock_core_class.create = AsyncMock(return_value=mock_core_instance)
        
        agent = PenguinAgent()
        assert agent._core == mock_core_instance
        mock_core_class.create.assert_called_once()

    @patch('penguin.agent.PenguinCore')
    def test_chat_method(self, mock_core_class):
        """Test the sync chat method."""
        mock_core_instance = AsyncMock()
        mock_core_instance.engine.run_single_turn = AsyncMock(
            return_value={"assistant_response": "Hello world!"}
        )
        mock_core_class.create = AsyncMock(return_value=mock_core_instance)
        
        agent = PenguinAgent()
        response = agent.chat("Hello")
        
        assert response == "Hello world!"
        mock_core_instance.engine.run_single_turn.assert_called_once()

    @patch('penguin.agent.PenguinCore')
    def test_run_task_method(self, mock_core_class):
        """Test the sync run_task method."""
        mock_core_instance = AsyncMock()
        mock_core_instance.engine.run_task = AsyncMock(
            return_value={"assistant_response": "Task done", "status": "completed"}
        )
        mock_core_class.create = AsyncMock(return_value=mock_core_instance)
        
        agent = PenguinAgent()
        result = agent.run_task("Complete this task")
        
        assert result["assistant_response"] == "Task done"
        assert result["status"] == "completed"
        mock_core_instance.engine.run_task.assert_called_once()


class TestPenguinAgentAsync:
    """Test the async PenguinAgentAsync wrapper."""
    
    @pytest.mark.asyncio
    async def test_agent_creation(self):
        """Test async agent creation."""
        with patch('penguin.agent.PenguinCore') as mock_core_class:
            mock_core_instance = AsyncMock()
            mock_core_class.create = AsyncMock(return_value=mock_core_instance)
            
            agent = await PenguinAgentAsync.create()
            assert agent._core == mock_core_instance
            mock_core_class.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_chat(self):
        """Test async chat method."""
        with patch('penguin.agent.PenguinCore') as mock_core_class:
            mock_core_instance = AsyncMock()
            mock_core_instance.engine.run_single_turn = AsyncMock(
                return_value={"assistant_response": "Async response"}
            )
            mock_core_class.create = AsyncMock(return_value=mock_core_instance)
            
            agent = await PenguinAgentAsync.create()
            response = await agent.chat("Test message")
            
            assert response == "Async response"
            mock_core_instance.engine.run_single_turn.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_run_task(self):
        """Test async run_task method."""
        with patch('penguin.agent.PenguinCore') as mock_core_class:
            mock_core_instance = AsyncMock()
            mock_core_instance.engine.run_task = AsyncMock(
                return_value={"assistant_response": "Async task done", "status": "completed"}
            )
            mock_core_class.create = AsyncMock(return_value=mock_core_instance)
            
            agent = await PenguinAgentAsync.create()
            result = await agent.run_task("Async task")
            
            assert result["assistant_response"] == "Async task done"
            mock_core_instance.engine.run_task.assert_called_once()


class TestBasicPenguinAgent:
    """Test the BasicPenguinAgent concrete implementation."""
    
    def test_agent_instantiation(self, basic_agent_config, mock_agent_components):
        """Test that BasicPenguinAgent can be instantiated."""
        agent = BasicPenguinAgent(
            agent_config=basic_agent_config,
            **mock_agent_components
        )
        assert agent.agent_config == basic_agent_config
        assert agent.conversation_manager == mock_agent_components['conversation_manager']

    @pytest.mark.asyncio
    async def test_run_method(self, basic_agent_config, mock_agent_components):
        """Test the run method implementation."""
        agent = BasicPenguinAgent(
            agent_config=basic_agent_config,
            **mock_agent_components
        )
        
        result = await agent.run("Test prompt", {"test": "context"})
        
        assert result["status"] == "completed"
        assert result["assistant_response"] == "Mock response"
        assert result["agent_type"] == "BasicPenguinAgent"
        mock_agent_components['conversation_manager'].process_message.assert_called_once_with("Test prompt")

    @pytest.mark.asyncio
    async def test_run_method_error_handling(self, basic_agent_config, mock_agent_components):
        """Test error handling in the run method."""
        mock_agent_components['conversation_manager'].process_message.side_effect = Exception("Test error")
        
        agent = BasicPenguinAgent(
            agent_config=basic_agent_config,
            **mock_agent_components
        )
        
        result = await agent.run("Test prompt")
        
        assert result["status"] == "error"
        assert "Test error" in result["error"]
        assert result["agent_type"] == "BasicPenguinAgent"

    @pytest.mark.asyncio 
    async def test_backward_compatibility_plan(self, basic_agent_config, mock_agent_components):
        """Test that the deprecated plan method still works."""
        agent = BasicPenguinAgent(
            agent_config=basic_agent_config,
            **mock_agent_components
        )
        
        result = await agent.plan("Test prompt")
        
        assert result["status"] == "completed"
        assert result["assistant_response"] == "Mock response"

    @pytest.mark.asyncio
    async def test_deprecated_methods(self, basic_agent_config, mock_agent_components):
        """Test that deprecated act and observe methods don't crash."""
        agent = BasicPenguinAgent(
            agent_config=basic_agent_config,
            **mock_agent_components
        )
        
        act_result = await agent.act({"action": "test"})
        assert act_result["status"] == "not_implemented"
        
        observe_result = await agent.observe({"results": "test"})
        assert observe_result["status"] == "not_implemented"


class TestAgentLauncher:
    """Test the AgentLauncher orchestration system."""
    
    @pytest.fixture
    def mock_core_with_components(self):
        """Mock core with all required components for launcher."""
        core = MagicMock()
        core.conversation_manager = AsyncMock()
        core.api_client = AsyncMock() 
        core.tool_manager = AsyncMock()
        core.action_executor = AsyncMock()
        return core

    def test_launcher_initialization(self, mock_core_with_components):
        """Test AgentLauncher initialization."""
        launcher = AgentLauncher(core=mock_core_with_components)
        assert launcher.core == mock_core_with_components
        assert launcher._agent_configs == {}

    def test_add_agent_config(self, mock_core_with_components, basic_agent_config):
        """Test adding agent configuration."""
        launcher = AgentLauncher(core=mock_core_with_components)
        launcher.add_agent(basic_agent_config)
        
        assert "test_agent" in launcher._agent_configs
        assert launcher._agent_configs["test_agent"] == basic_agent_config

    @pytest.mark.asyncio
    async def test_invoke_agent(self, mock_core_with_components, basic_agent_config):
        """Test invoking an agent through the launcher."""
        launcher = AgentLauncher(core=mock_core_with_components)
        launcher.add_agent(basic_agent_config)
        
        # Mock the conversation manager to return a valid response
        mock_core_with_components.conversation_manager.process_message = AsyncMock(
            return_value={"assistant_response": "Launcher test response", "action_results": []}
        )
        
        result = await launcher.invoke("test_agent", "Test prompt", caller="test")
        
        assert result["status"] == "completed"
        assert result["assistant_response"] == "Launcher test response"

    @pytest.mark.asyncio
    async def test_invoke_nonexistent_agent(self, mock_core_with_components):
        """Test invoking a non-existent agent raises error."""
        launcher = AgentLauncher(core=mock_core_with_components)
        
        with pytest.raises(ValueError, match="Agent configuration 'nonexistent' not found"):
            await launcher.invoke("nonexistent", "Test prompt")

    def test_sandbox_warning(self, mock_core_with_components):
        """Test that sandbox execution logs a warning for now."""
        sandbox_config = AgentConfig(
            name="sandbox_agent", 
            type="penguin.agent.basic_agent.BasicPenguinAgent",
            description="Sandbox test agent",
            security=SecurityConfig(sandbox_type="docker")
        )
        
        launcher = AgentLauncher(core=mock_core_with_components)
        launcher.add_agent(sandbox_config)
        
        with patch('penguin.agent.launcher.logger') as mock_logger:
            asyncio.run(launcher.invoke("sandbox_agent", "Test"))
            mock_logger.warning.assert_called()


class TestResourceSnapshots:
    """Test resource monitoring and snapshots."""
    
    @pytest.mark.asyncio
    async def test_resource_snapshot_updates(self, basic_agent_config, mock_agent_components):
        """Test that agents receive resource updates."""
        from penguin.engine import ResourceSnapshot
        
        agent = BasicPenguinAgent(
            agent_config=basic_agent_config, 
            **mock_agent_components
        )
        
        snapshot = ResourceSnapshot(tokens_prompt=100, tokens_completion=50, wall_clock_sec=5.0)
        
        await agent.update_resource_snapshot(snapshot)
        
        assert agent.current_resources.tokens_prompt == 100
        assert agent.current_resources.tokens_completion == 50
        assert agent.current_resources.wall_clock_sec == 5.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])