from setuptools import setup, find_packages
import sys
import os

# Add src to path so we can import version
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from secontrol._version import __version__

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="secontrol",
    version=__version__,
    author="secontrol contributors",
    description="Space Engineers Redis helper utilities",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/rootfabric/secontrol",
    project_urls={
        "Homepage": "https://www.outenemy.ru/se",
        "Repository": "https://github.com/rootfabric/secontrol",
        "Issues": "https://github.com/rootfabric/secontrol/issues",
    },
    license="MIT",
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Topic :: Utilities"
    ],
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    python_requires=">=3.9",
    install_requires=[
        "redis>=4.5",
        "python-dotenv>=1.0",
        "numpy>=1.26"
    ],
    extras_require={
        "dev": [
            "pytest>=7",
            "build>=1.2",
            "twine>=4.0"
        ]
    },
    include_package_data=True,
    zip_safe=False,
)
