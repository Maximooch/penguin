#!/usr/bin/env python3
"""Main entry point for the Project Management Application."""

from project_manager import ProjectManager

def main():
    """Run the main application loop."""
    project_manager = ProjectManager()
    
    while True:
        print("\nProject Management Application")
        print("1. Create a new project")
        print("2. List all projects")
        print("3. Add a task to a project")
        print("4. List tasks for a project")
        print("5. Update task status")
        print("6. Exit")
        
        choice = input("Enter your choice (1-6): ")
        
        if choice == '1':
            name = input("Enter project name: ")
            description = input("Enter project description: ")
            project_manager.create_project(name, description)
        elif choice == '2':
            project_manager.list_projects()
        elif choice == '3':
            project_id = int(input("Enter project ID: "))
            task_name = input("Enter task name: ")
            task_description = input("Enter task description: ")
            deadline = input("Enter task deadline (YYYY-MM-DD): ")
            project_manager.add_task(project_id, task_name, task_description, deadline)
        elif choice == '4':
            project_id = int(input("Enter project ID: "))
            project_manager.list_tasks(project_id)
        elif choice == '5':
            task_id = int(input("Enter task ID: "))
            new_status = input("Enter new status (todo/in_progress/done): ")
            project_manager.update_task_status(task_id, new_status)
        elif choice == '6':
            print("Goodbye!")
            break
        else:
            print("Invalid choice. Please try again.")

if __name__ == "__main__":
    main()