# Sets up Penguin using UV package manager

# Create virtual environment with Python 3.10
import subprocess
import sys
import os
from tqdm import tqdm
import time

def run_with_progress(description, command):
    print(f"\n🐧 {description}")
    with tqdm(total=100, 
             bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt}',
             colour='cyan') as pbar:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        while process.poll() is None:
            time.sleep(0.1)
            pbar.update(1)
        pbar.n = 100
        pbar.refresh()
    
    if process.returncode != 0:
        print(f"❌ Error during {description.lower()}")
        sys.exit(1)
    print(f"✅ {description} complete!")

def main():
    print("\n🐧 Setting up Penguin Development Environment\n")
    
    # Create virtual environment
    run_with_progress(
        "Creating virtual environment",
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
        subprocess.run(["cd", "penguin"])
        subprocess.run(["uv", "run", "penguin/main.py"])

if __name__ == "__main__":
    main()