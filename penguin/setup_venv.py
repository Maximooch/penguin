
import os
import subprocess
import sys
import venv

# print ("Penguin setup venv process started")

def create_venv(venv_path):
    venv.create(venv_path, with_pip=True)

def install_requirements(venv_path):
    if os.name == 'nt':  # Windows
        pip_path = os.path.join(venv_path, 'Scripts', 'pypy3')
    else:  # Unix-like systems
        pip_path = os.path.join(venv_path, 'bin', 'pypy3')
    requirements_path = os.path.join(os.path.dirname(__file__), 'requirements.txt')
    subprocess.check_call([pip_path, '-m', 'pip', 'install', '-r', requirements_path])

def main():
    venv_path = os.path.join(os.path.dirname(__file__), 'penguin_pypy_venv')
    create_venv(venv_path)
    install_requirements(venv_path)
    print(f"PyPy virtual environment created and packages installed at: {venv_path}")

if __name__ == "__main__":
    main()


# def ensure_venv():
#     venv_path = os.path.join(os.path.dirname(__file__), 'penguin_venv')
#     print(f"Checking for virtual environment at: {venv_path}")
    
#     if not os.path.exists(venv_path):
#         print("Virtual environment not found. Creating...")
#         venv.create(venv_path, with_pip=True)
    
#     # Activate the virtual environment
#     if os.name == 'nt':  # Windows
#         activate_this = os.path.join(venv_path, 'Scripts', 'activate_this.py')
#         python_exe = os.path.join(venv_path, 'Scripts', 'python.exe')
#     else:  # Unix-like systems
#         activate_this = os.path.join(venv_path, 'bin', 'activate_this.py')
#         python_exe = os.path.join(venv_path, 'bin', 'python')
    
#     if os.path.exists(activate_this):
#         print(f"Activating virtual environment using: {activate_this}")
#         exec(open(activate_this).read(), {'__file__': activate_this})
#     else:
#         print(f"Warning: activate_this.py not found at {activate_this}")
#         print(f"Using Python executable: {python_exe}")
#         os.execv(python_exe, [python_exe] + sys.argv)
    
#     # Update sys.path
#     site.main()
    
#     # Install required packages
#     requirements_path = os.path.join(os.path.dirname(__file__), 'requirements.txt')
#     print(f"Installing requirements from: {requirements_path}")
#     subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", requirements_path])
    
#     print(f"Python executable: {sys.executable}")
#     print(f"sys.prefix: {sys.prefix}")
#     print(f"sys.path: {sys.path}")
#     print(f"Using virtual environment: {venv_path}")

#     # Check if litellm is installed
#     try:
#         import litellm
#         print("litellm is installed and importable")
#     except ImportError as e:
#         print(f"Error importing litellm: {e}")
#         print("Attempting to install litellm...")
#         subprocess.check_call([sys.executable, "-m", "pip", "install", "litellm"])
#         print("litellm installation attempt complete")

#     # Print the contents of site-packages
#     site_packages = site.getsitepackages()[0]
#     print(f"Contents of site-packages: {os.listdir(site_packages)}")

# # Call ensure_venv() at the beginning of the script
# ensure_venv()
