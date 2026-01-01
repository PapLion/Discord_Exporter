from setuptools import setup, find_packages

setup(
    name="discord_exporter_api",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        'fastapi>=0.68.0',
        'uvicorn>=0.15.0',
        'python-jose[cryptography]>=3.3.0',
        'passlib[bcrypt]>=1.7.4',
        'python-multipart>=0.0.5',
        'requests>=2.26.0',
        'pydantic>=1.8.0',
    ],
    extras_require={
        'dev': [
            'pytest>=6.0.0',
            'pytest-cov>=2.0.0',
            'pytest-mock>=3.6.1',
        ],
    },
    python_requires='>=3.7',
)
