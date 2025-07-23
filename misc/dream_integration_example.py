"""Dream Workflow Integration Example for Penguin.

This example demonstrates how to use the dream workflow implementation
to achieve the vision described in dream.md points 0-4.
"""

import asyncio
import logging
from pathlib import Path

# Assuming the user has their existing Penguin components
from penguin.core import PenguinCore
from penguin.project.dream_workflow import DreamWorkflow, execute_dream_workflow

logger = logging.getLogger(__name__)


async def example_dream_workflow():
    """Example of executing the complete dream workflow."""
    
    # Initialize your existing Penguin core
    workspace_path = Path("workspace")
    core = PenguinCore(workspace_path=workspace_path)
    
    # Make sure you have the Engine initialized
    if not hasattr(core, 'engine') or not core.engine:
        logger.error("Engine is required for dream workflow")
        return
    
    # Example project specification (Point 0: Natural language description)
    project_specification = """
    Create a simple web-based task manager application that allows users to:
    
    1. Add new tasks with titles and descriptions
    2. Mark tasks as completed or pending
    3. Delete tasks they no longer need
    4. View all tasks in a clean, organized interface
    
    The application should be built with HTML, CSS, and JavaScript.
    It should have a modern, responsive design that works on mobile devices.
    Include basic form validation and local storage to persist tasks.
    
    The final deliverable should include:
    - A main HTML file (index.html)
    - CSS stylesheet for styling
    - JavaScript file for functionality
    - Simple documentation explaining how to use the app
    """
    
    try:
        # Execute the complete dream workflow
        logger.info("Starting dream workflow execution...")
        
        # Option 1: Use the convenience function
        result = await execute_dream_workflow(
            specification=project_specification,
            engine=core.engine,
            project_manager=core.project_manager,
            conversation_manager=core.conversation_manager,
            run_mode=core.run_mode,
            workspace_path=workspace_path,
            project_name="Web Task Manager",
            auto_execute=True,
            require_approval=True
        )
        
        # Option 2: Or use the class directly for more control
        # workflow = DreamWorkflow(
        #     engine=core.engine,
        #     project_manager=core.project_manager,
        #     conversation_manager=core.conversation_manager,
        #     run_mode=core.run_mode,
        #     workspace_path=workspace_path
        # )
        # result = await workflow.execute_dream_workflow(
        #     specification=project_specification,
        #     project_name="Web Task Manager"
        # )
        
        print("\n🎉 Dream Workflow Results:")
        print(f"Status: {result['status']}")
        print(f"Project ID: {result.get('project_id', 'N/A')}")
        print(f"Tasks Completed: {result.get('tasks_completed', 0)}/{result.get('total_tasks', 0)}")
        
        # Show step-by-step results
        for step_name, step_result in result.get('steps', {}).items():
            print(f"\n📋 Step {step_name}:")
            if isinstance(step_result, dict):
                print(f"  Status: {step_result.get('status', 'Unknown')}")
                print(f"  Message: {step_result.get('message', 'No message')}")
        
        # If tasks were executed and require approval, check approval status
        if result.get('project_id') and result.get('steps', {}).get('3_4_validation_approval'):
            await check_approval_status(core, result['project_id'])
            
        return result
        
    except Exception as e:
        logger.error(f"Dream workflow failed: {e}")
        return {"status": "error", "message": str(e)}


async def check_approval_status(core, project_id: str):
    """Example of checking and finalizing approval status."""
    
    # Initialize workflow for approval checking
    workflow = DreamWorkflow(
        engine=core.engine,
        project_manager=core.project_manager,
        conversation_manager=core.conversation_manager,
        run_mode=core.run_mode,
        workspace_path=core.workspace_path
    )
    
    print("\n🔍 Checking approval status...")
    
    # Check current approval status
    approval_status = await workflow.check_and_finalize_approvals(project_id)
    
    if approval_status['status'] == 'completed':
        results = approval_status['results']
        print(f"✅ Checked {results['checked_tasks']} tasks")
        print(f"📝 Approved: {results['approved_tasks']}")
        print(f"❌ Rejected: {results['rejected_tasks']}")
        print(f"🎯 Finalized: {results['finalized_tasks']}")
        
        # Show individual task statuses
        for task_status in results['task_statuses']:
            status_emoji = {
                'approved': '✅',
                'rejected': '❌',
                'pending': '⏳',
                'error': '🔥'
            }.get(task_status['approval_status'], '❓')
            
            print(f"  {status_emoji} {task_status['task_title']}: {task_status['approval_status']}")
            
            if task_status['approval_status'] == 'rejected':
                print(f"    Reason: {task_status.get('rejection_reason', 'No reason provided')}")


async def manual_approval_workflow_example():
    """Example of manually approving tasks step by step."""
    
    workspace_path = Path("workspace")
    core = PenguinCore(workspace_path=workspace_path)
    
    # Simple specification for testing
    simple_spec = """
    Create a simple Python script that:
    1. Asks the user for their name
    2. Prints a personalized greeting
    3. Saves the greeting to a text file
    """
    
    # Step 1: Parse specification only (no auto-execution)
    workflow = DreamWorkflow(
        engine=core.engine,
        project_manager=core.project_manager,
        conversation_manager=core.conversation_manager,
        run_mode=core.run_mode,
        workspace_path=workspace_path
    )
    
    result = await workflow.execute_dream_workflow(
        specification=simple_spec,
        project_name="Simple Greeting Script",
        auto_execute=False,  # Don't execute automatically
        require_approval=True
    )
    
    if result['status'] != 'completed':
        print(f"❌ Failed to parse specification: {result.get('error')}")
        return
    
    project_id = result['project_id']
    print(f"✅ Project created: {project_id}")
    print(f"📋 Tasks created: {result['total_tasks']}")
    
    # Step 2: Manually execute tasks one by one
    from penguin.project.models import TaskStatus
    active_tasks = core.project_manager.list_tasks(
        project_id=project_id,
        status=TaskStatus.ACTIVE
    )
    
    for task in active_tasks:
        print(f"\n🚀 Executing task: {task.title}")
        
        # Execute individual task
        exec_result = await workflow.task_executor.execute_task_with_context(task.id)
        
        print(f"   Status: {exec_result.get('status')}")
        
        if exec_result.get('status') == 'success':
            # Process validation and approval
            task_approval = await workflow._process_single_task_approval(task)
            print(f"   Validation: {'✅ Passed' if task_approval.get('validated') else '❌ Failed'}")
            print(f"   Approval Status: {task_approval.get('approval_status')}")
            
            if task_approval.get('approval_file'):
                print(f"   📄 Review file: {task_approval['approval_file']}")
                print("   👉 Delete the approval file to approve, or edit it to reject")


def human_approval_instructions():
    """Instructions for humans on how to approve/reject tasks."""
    
    instructions = """
    🔧 HUMAN APPROVAL WORKFLOW INSTRUCTIONS
    
    When Penguin completes a task, it will:
    1. ✅ Validate the deliverables automatically
    2. 🔀 Create a Git branch for the task
    3. 💾 Commit the changes with validation results
    4. 📄 Create an approval request file
    
    To APPROVE a task:
    • Delete the APPROVAL_REQUEST_[task_id].md file
    • Commit the deletion: git add . && git commit -m "Approve task"
    
    To REJECT a task:
    • Edit the APPROVAL_REQUEST_[task_id].md file
    • Add your rejection reason in the designated section
    • Commit the changes: git add . && git commit -m "Reject task with reason"
    
    To check status:
    • Run the approval checking workflow
    • Approved tasks will be automatically merged to main branch
    
    🎯 The Goal: This creates a verifiable, version-controlled record of AI work
    that humans can review and approve, achieving the dream.md vision!
    """
    
    print(instructions)


if __name__ == "__main__":
    # Example usage
    print("🐧 Penguin Dream Workflow Example\n")
    
    # Show instructions first
    human_approval_instructions()
    
    # Run the example
    # asyncio.run(example_dream_workflow())
    
    # Or run the manual workflow
    # asyncio.run(manual_approval_workflow_example())
    
    print("\n✨ Dream workflow implementation complete!")
    print("This achieves all points 0-4 from dream.md:")
    print("  0. ✅ Natural language project specification parsing")
    print("  1. ✅ Context prioritization and task breakdown")
    print("  2. ✅ Agent delegation through RunMode")
    print("  3. ✅ Verifiable rewards through testing deliverables")
    print("  4. ✅ Human approval via version control workflows") 