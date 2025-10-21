/**
 * Project & Task API Client
 *
 * Makes HTTP REST API calls to manage projects and tasks
 */

export interface Project {
  id: string;
  name: string;
  description?: string;
  created_at: string;
  status: string;
}

export interface Task {
  id: string;
  title: string;
  description?: string;
  project_id: string;
  status: string;
  priority?: number;
  created_at: string;
}

export interface CreateProjectRequest {
  name: string;
  description?: string;
}

export interface CreateTaskRequest {
  name: string;
  description?: string;
  project_id?: string;
}

export class ProjectAPI {
  private baseUrl: string;

  constructor(baseUrl: string = 'http://localhost:8000') {
    this.baseUrl = baseUrl;
  }

  /**
   * Create a new project
   */
  async createProject(name: string, description?: string): Promise<Project> {
    const response = await fetch(`${this.baseUrl}/api/v1/projects`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ name, description }),
    });
    if (!response.ok) {
      throw new Error(`Failed to create project: ${response.statusText}`);
    }
    return (await response.json()) as Project;
  }

  /**
   * List all projects
   */
  async listProjects(): Promise<Project[]> {
    const response = await fetch(`${this.baseUrl}/api/v1/projects`);
    if (!response.ok) {
      throw new Error(`Failed to list projects: ${response.statusText}`);
    }
    const data: any = await response.json();
    return (data.projects || []) as Project[];
  }

  /**
   * Create a task (requires project_id)
   */
  async createTask(title: string, project_id: string, description?: string, priority?: number): Promise<Task> {
    const response = await fetch(`${this.baseUrl}/api/v1/tasks`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        title,
        project_id,
        description,
        priority: priority || 1
      }),
    });
    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`Failed to create task: ${response.statusText} - ${errorText}`);
    }
    return (await response.json()) as Task;
  }

  /**
   * List all tasks
   */
  async listTasks(): Promise<Task[]> {
    const response = await fetch(`${this.baseUrl}/api/v1/tasks`);
    if (!response.ok) {
      throw new Error(`Failed to list tasks: ${response.statusText}`);
    }
    const data: any = await response.json();
    return (data.tasks || []) as Task[];
  }
}
