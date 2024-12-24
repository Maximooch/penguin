# Sets up Penguin using UV package manager

# Create virtual environment with Python 3.10
import subprocess
import sys
import os
from tqdm import tqdm
import time

def run_with_progress(description, command):
    print(f"\n🐧 {description}")
    print(f"Running command: {' '.join(command)}")  # Debug: Show command being run
    
    with tqdm(total=100, 
             bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt}',
             colour='cyan') as pbar:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True  # Enable text mode for readable output
        )
        
        # Collect output while running
        stdout = []
        stderr = []
        while process.poll() is None:
            # Read any available output
            if process.stdout:
                line = process.stdout.readline()
                if line:
                    stdout.append(line)
            if process.stderr:
                line = process.stderr.readline()
                if line:
                    stderr.append(line)
            
            time.sleep(0.1)
            pbar.update(1)
        
        # Get any remaining output
        out, err = process.communicate()
        if out:
            stdout.append(out)
        if err:
            stderr.append(err)
        
        pbar.n = 100
        pbar.refresh()
    
    if process.returncode != 0:
        print(f"\n❌ Error during {description.lower()}")
        print("\nCommand output:")
        print("".join(stdout))
        print("\nError output:")
        print("".join(stderr))
        print(f"\nExit code: {process.returncode}")
        sys.exit(1)
    
    print(f"✅ {description} complete!")
    # Debug: Show successful output
    if stdout:
        print("\nCommand output:")
        print("".join(stdout))

def main():
    print("\n🐧 Setting up Penguin Development Environment\n")
    
    # Debug: Show current working directory
    print(f"Current working directory: {os.getcwd()}")
    print(f"Requirements file exists: {os.path.exists('requirements.txt')}")
    
    # Create virtual environment
    run_with_progress(
        "Creating virtual environment",
        os.chdir('penguin')
        ["uv", "venv", "--python", "3.10"]
    )
    
    # Install requirements
    run_with_progress(
        "Installing dependencies",
        ["uv", "pip", "sync", "requirements.txt"]
    )
    
    print("\n✨ Setup complete! Happy coding! 🐧")
    
    # Ask if user wants to launch Penguin
    launch = input("\nWould you like to launch Penguin now? (y/N): ").lower().strip()
    if launch == 'y':
        print("\n🚀 Launching Penguin...\n")
        # Change directory using os.chdir instead of subprocess.run
        # os.chdir('penguin')
        subprocess.run(["uv", "run", "main.py"])

if __name__ == "__main__":
    main()