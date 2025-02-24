import json
from penguin.utils.parser import CodeActAction, ActionType

class VerificationManager:
    """Handles task completion verification"""
    
    def __init__(self, tool_manager, llm_client):
        self.tool_manager = tool_manager
        self.llm_client = llm_client

    async def verify(self, context: str, actions: list) -> bool:
        """Execute verification checks"""
        # 1. Automated test execution
        test_pass = await self._run_automated_tests(actions)
        
        # 2. LLM success analysis
        llm_verdict = await self._llm_success_check(context, actions)
        
        return test_pass and llm_verdict

    async def _run_automated_tests(self, actions: list) -> bool:
        """Execute relevant tests from actions"""
        # Convert CodeActActions to tool manager format
        test_actions = [
            {
                "type": a.action_type.value,
                "params": a.params
            }
            for a in actions 
            if a.action_type == ActionType.EXECUTE_TEST  # Use enum comparison
        ]
        
        if not test_actions:
            return True  # No tests to run
            
        results = await self.tool_manager.execute_batch(test_actions)
        return all(r['success'] for r in results)

    async def _llm_success_check(self, context: str, actions: list) -> bool:
        """LLM-based success verification"""
        # Serialize CodeActActions
        serialized_actions = [
            {
                "type": a.action_type.value,
                "params": a.params
            }
            for a in actions
        ]
        
        prompt = f"""Verify if these actions fully complete the task:
        
        Context: {context}
        Actions: {json.dumps(serialized_actions)}
        
        Answer ONLY 'YES' or 'NO'"""
        
        response = await self.llm_client.create_completion(
            prompt=prompt,
            max_tokens=3
        )
        return "YES" in response.upper()