import os
import subprocess
import sys
import venv

# print ("Penguin setup venv process started")

def create_venv(venv_path):
    venv.create(venv_path, with_pip=True)

def install_requirements(venv_path):
    if os.name == 'nt':  # Windows
        pip_path = os.path.join(venv_path, 'Scripts', 'pip')
    else:  # Unix-like systems
        pip_path = os.path.join(venv_path, 'bin', 'pip')
    requirements_path = os.path.join(os.path.dirname(__file__), 'requirements.txt')
    subprocess.check_call([pip_path, 'install', '-r', requirements_path])

def main():
    venv_path = os.path.join(os.path.dirname(__file__), 'penguin_venv')
    create_venv(venv_path)
    install_requirements(venv_path)
    print(f"Virtual environment created and packages installed at: {venv_path}")

if __name__ == "__main__":
    main()