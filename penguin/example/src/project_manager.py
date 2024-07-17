"""Module containing the ProjectManager class for managing projects and tasks."""

from typing import List, Optional
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import sessionmaker, relationship, declarative_base
from sqlalchemy.exc import SQLAlchemyError

Base = declarative_base()

class Project(Base):
    """SQLAlchemy model for the projects table."""
    __tablename__ = 'projects'
    
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    description = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    tasks = relationship("Task", back_populates="project")

class Task(Base):
    """SQLAlchemy model for the tasks table."""
    __tablename__ = 'tasks'
    
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    description = Column(String)
    status = Column(String, default='todo')
    deadline = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    project_id = Column(Integer, ForeignKey('projects.id'))
    project = relationship("Project", back_populates="tasks")

class ProjectManager:
    """Handles project and task operations using SQLAlchemy."""

    def __init__(self, db_path: str = 'sqlite:///projects.db'):
        """Initialize the ProjectManager with a database connection."""
        self.engine = create_engine(db_path)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def create_project(self, name: str, description: str) -> None:
        """Create a new project."""
        session = self.Session()
        try:
            new_project = Project(name=name, description=description)
            session.add(new_project)
            session.commit()
            print(f"Project '{name}' created successfully.")
        except SQLAlchemyError as e:
            session.rollback()
            print(f"Error creating project: {str(e)}")
        finally:
            session.close()

    def list_projects(self) -> None:
        """List all projects."""
        session = self.Session()
        try:
            projects = session.query(Project).all()
            if not projects:
                print("No projects found.")
            else:
                for project in projects:
                    print(f"ID: {project.id}, Name: {project.name}, Description: {project.description}")
        except SQLAlchemyError as e:
            print(f"Error listing projects: {str(e)}")
        finally:
            session.close()

    def add_task(self, project_id: int, name: str, description: str, deadline: str) -> None:
        """Add a new task to a project."""
        session = self.Session()
        try:
            project = session.query(Project).filter_by(id=project_id).first()
            if not project:
                print(f"Project with ID {project_id} not found.")
                return
            
            deadline_date = datetime.strptime(deadline, "%Y-%m-%d")
            new_task = Task(name=name, description=description, deadline=deadline_date, project=project)
            session.add(new_task)
            session.commit()
            print(f"Task '{name}' added to project '{project.name}' successfully.")
        except ValueError:
            print("Invalid date format. Please use YYYY-MM-DD.")
        except SQLAlchemyError as e:
            session.rollback()
            print(f"Error adding task: {str(e)}")
        finally:
            session.close()

    def list_tasks(self, project_id: int) -> None:
        """List all tasks for a specific project."""
        session = self.Session()
        try:
            project = session.query(Project).filter_by(id=project_id).first()
            if not project:
                print(f"Project with ID {project_id} not found.")
                return
            
            if not project.tasks:
                print(f"No tasks found for project '{project.name}'.")
            else:
                print(f"Tasks for project '{project.name}':")
                for task in project.tasks:
                    print(f"ID: {task.id}, Name: {task.name}, Status: {task.status}, Deadline: {task.deadline}")
        except SQLAlchemyError as e:
            print(f"Error listing tasks: {str(e)}")
        finally:
            session.close()

    def update_task_status(self, task_id: int, new_status: str) -> None:
        """Update the status of a task."""
        session = self.Session()
        try:
            task = session.query(Task).filter_by(id=task_id).first()
            if not task:
                print(f"Task with ID {task_id} not found.")
                return
            
            if new_status not in ['todo', 'in_progress', 'done']:
                print("Invalid status. Please use 'todo', 'in_progress', or 'done'.")
                return
            
            task.status = new_status
            session.commit()
            print(f"Task '{task.name}' status updated to '{new_status}' successfully.")
        except SQLAlchemyError as e:
            session.rollback()
            print(f"Error updating task status: {str(e)}")
        finally:
            session.close()