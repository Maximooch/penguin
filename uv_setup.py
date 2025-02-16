# Sets up Penguin using UV package manager

# Create virtual environment with Python 3.10
import os
import subprocess
import sys


def run_command(description, command):
    print(f"\n🐧 {description}")
    print(f"Running command: {' '.join(command)}")

    # Run command without capturing output to show real-time progress
    result = subprocess.run(command, capture_output=False, text=True)

    if result.returncode != 0:
        print(f"\n❌ Error during {description.lower()}")
        sys.exit(1)

    print(f"✅ {description} complete!")


def main():
    print("\n🐧 Setting up Penguin Development Environment\n")

    # Debug: Show current working directory
    print(f"Current working directory: {os.getcwd()}")
    print(f"Requirements file exists: {os.path.exists('requirements.txt')}")

    # Create virtual environment with Python 3.10
    run_command("Creating virtual environment", ["uv", "venv", "--python", "3.10"])

    # Install requirements
    run_command(
        "Installing dependencies", ["uv", "pip", "install", "-r", "requirements.txt"]
    )

    print("\n✨ Setup complete! Happy coding! 🐧")

    # Ask if user wants to launch Penguin
    launch = input("\nWould you like to launch Penguin now? (y/N): ").lower().strip()
    if launch == "y":
        print("\n🚀 Launching Penguin...\n")
        subprocess.run(["uv", "run", "main.py"])


if __name__ == "__main__":
    main()
