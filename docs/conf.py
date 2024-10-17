import os
import sys
sys.path.insert(0, os.path.abspath('..'))

project = 'Penguin AI Assistant'
copyright = '2024, LinkAI'
author = 'Maximus Putnam'

extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.napoleon',
    'sphinx.ext.viewcode',
    'myst_parser',
]

templates_path = ['_templates']
exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store']

html_theme = 'sphinx_rtd_theme'
html_static_path = ['_static']

source_suffix = {
    '.rst': 'restructuredtext',
    '.md': 'markdown',
}