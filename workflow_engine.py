import asyncio
import logging
from typing import Callable, Awaitable, Any, Dict, List

logger = logging.getLogger(__name__)

# Define the type for a workflow step function. Each step takes a context dict and returns an updated context.
WorkflowStep = Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]


class Workflow:
    """Class representing a multi-step workflow."""
    def __init__(self, steps: List[WorkflowStep]):
        self.steps = steps

    async def run(self, initial_context: Dict[str, Any]) -> Dict[str, Any]:
        context = initial_context
        for step in self.steps:
            try:
                context = await step(context)
            except Exception as e:
                logger.error(f"Error in workflow step: {e}")
                context['error'] = str(e)
                break
        return context


class WorkflowEngine:
    """Engine to register and run workflows."""
    def __init__(self):
        self.workflows = {}

    def register_workflow(self, name: str, workflow: Workflow):
        self.workflows[name] = workflow
        logger.info(f"Registered workflow: {name}")

    async def run_workflow(self, name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        if name not in self.workflows:
            raise ValueError(f"Workflow {name} not registered.")
        logger.info(f"Running workflow: {name}")
        result = await self.workflows[name].run(context)
        return result


# Example step functions for demonstration
async def preprocess_step(context: Dict[str, Any]) -> Dict[str, Any]:
    # Perform some preliminary processing on the context
    context['preprocess'] = 'Preprocessed data'
    return context


async def execution_step(context: Dict[str, Any]) -> Dict[str, Any]:
    # Execute the main task
    context['execution'] = 'Executed task'
    return context


async def postprocess_step(context: Dict[str, Any]) -> Dict[str, Any]:
    # Finalize and format the result
    context['postprocess'] = 'Finalized result'
    return context


# If this module is run as a script, demonstrate a simple workflow run.
if __name__ == '__main__':
    async def demo():
        engine = WorkflowEngine()
        demo_workflow = Workflow(steps=[preprocess_step, execution_step, postprocess_step])
        engine.register_workflow('demo', demo_workflow)
        result = await engine.run_workflow('demo', {})
        print('Workflow result:', result)
    
    asyncio.run(demo()) 