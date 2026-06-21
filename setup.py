from setuptools import setup, find_packages

setup(
    name="mslearn-downloader",
    version="1.0.0",
    packages=find_packages(),
    install_requires=[
        "requests",
        "beautifulsoup4",
        "lxml",
        "markdownify",
        "click",
        "rich",
        "pyyaml",
        "playwright",
        "pillow",
        "cairosvg",
        "flask",
    ],
    entry_points={
        "console_scripts": [
            "mslearn-dl=mslearn_downloader.cli:main",
        ],
    },
)