"""Test module for the ProjectManager class."""

import pytest
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.project_manager import ProjectManager, Project, Task, Base

@pytest.fixture(scope="function")
def project_manager():
    """Fixture to create a ProjectManager instance with an in-memory SQLite database."""
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    pm = ProjectManager('sqlite:///:memory:')
    
    # Create a sample project and task
    session = Session()
    project = Project(name="Test Project", description="A test project")
    session.add(project)
    task = Task(
        name="Test Task",
        description="A test task",
        status="todo",
        deadline=datetime.utcnow() + timedelta(days=7),
        project=project
    )
    session.add(task)
    session.commit()
    session.close()
    
    yield pm

def test_create_project(project_manager):
    """Test creating a new project."""
    project_manager.create_project("New Project", "A new test project")
    
    session = project_manager.Session()
    projects = session.query(Project).all()
    session.close()
    
    assert len(projects) == 2
    assert projects[1].name == "New Project"
    assert projects[1].description == "A new test project"

def test_list_projects(project_manager, capsys):
    """Test listing all projects."""
    project_manager.list_projects()
    captured = capsys.readouterr()
    assert "ID: 1, Name: Test Project, Description: A test project" in captured.out

def test_add_task(project_manager):
    """Test adding a new task to a project."""
    project_manager.add_task(1, "New Task", "A new test task", "2023-12-31")
    
    session = project_manager.Session()
    tasks = session.query(Task).filter_by(project_id=1).all()
    session.close()
    
    assert len(tasks) == 2
    assert tasks[1].name == "New Task"
    assert tasks[1].description == "A new test task"
    assert tasks[1].deadline.strftime("%Y-%m-%d") == "2023-12-31"

def test_list_tasks(project_manager, capsys):
    """Test listing tasks for a specific project."""
    project_manager.list_tasks(1)
    captured = capsys.readouterr()
    assert "ID: 1, Name: Test Task, Status: todo" in captured.out

def test_update_task_status(project_manager):
    """Test updating the status of a task."""
    project_manager.update_task_status(1, "in_progress")
    
    session = project_manager.Session()
    task = session.query(Task).filter_by(id=1).first()
    session.close()
    
    assert task.status == "in_progress"

def test_invalid_project_id(project_manager, capsys):
    """Test behavior with an invalid project ID."""
    project_manager.list_tasks(999)
    captured = capsys.readouterr()
    assert "Project with ID 999 not found." in captured.out

def test_invalid_task_id(project_manager, capsys):
    """Test behavior with an invalid task ID."""
    project_manager.update_task_status(999, "done")
    captured = capsys.readouterr()
    assert "Task with ID 999 not found." in captured.out

def test_invalid_task_status(project_manager, capsys):
    """Test behavior with an invalid task status."""
    project_manager.update_task_status(1, "invalid_status")
    captured = capsys.readouterr()
    assert "Invalid status. Please use 'todo', 'in_progress', or 'done'." in captured.out