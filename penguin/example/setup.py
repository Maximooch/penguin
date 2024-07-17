from setuptools import setup, find_packages

setup(
    name="project_management",
    version="0.1.0",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    install_requires=[
        "sqlalchemy>=1.4.46,<2.0.0",
    ],
    extras_require={
        "dev": [
            "pytest>=7.3.1,<8.0.0",
            "black>=23.3.0,<24.0.0",
            "flake8>=6.0.0,<7.0.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "project_management=main:main",
        ],
    },
    author="Your Name",
    author_email="your.email@example.com",
    description="A simple project management application",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    url="https://github.com/yourusername/project_management",
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
    ],
)