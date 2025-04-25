#!/usr/bin/env python
"""
Script to run the event system test with the correct Python path.
Run with: python run_test_events.py
"""

import os
import sys
import subprocess

def main():
    # Get the root project directory (where this script is)
    project_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Add the parent directory to Python path so imports work
    parent_dir = os.path.dirname(project_dir)
    
    # Run the test_events_runner.py script with the correct PYTHONPATH
    env = os.environ.copy()
    env["PYTHONPATH"] = parent_dir + os.pathsep + env.get("PYTHONPATH", "")
    
    print(f"Setting PYTHONPATH to include: {parent_dir}")
    print(f"Current directory: {os.getcwd()}")
    
    # Run the test_events_runner.py script
    script_path = os.path.join(project_dir, "test_events_runner.py")
    print(f"Running: {script_path}")
    
    result = subprocess.run(
        [sys.executable, script_path],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    
    # Print the output
    print("\n--- STDOUT ---")
    print(result.stdout)
    
    print("\n--- STDERR ---")
    print(result.stderr)
    
    print(f"\nExit code: {result.returncode}")

if __name__ == "__main__":
    main() 