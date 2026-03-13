# Contributing to Discord Exporter

Thank you for your interest in contributing! This document outlines the process for contributing to this project.

## Development Prerequisites

Before you begin, ensure you have the following installed:

- **Python 3.11+** - The project requires Python 3.11 or higher
- **Git** - For version control
- **Redis** (optional) - For async job processing

## Development Setup

### 1. Fork and Clone the Repository

```bash
# Fork the repository on GitHub, then clone your fork
git clone https://github.com/YOUR_USERNAME/Discord_Exporter.git
cd Discord_Exporter
```

### 2. Create a Virtual Environment

```bash
# Create a virtual environment
python -m venv venv

# Activate it
# On macOS/Linux:
source venv/bin/activate
# On Windows:
venv\Scripts\activate
```

### 3. Install Dependencies

```bash
# Install the package in development mode
cd api
pip install -e .
pip install -r requirements.txt
pip install -r requirements-dev.txt  # If available
```

### 4. Set Up Environment Variables

```bash
# Copy the example environment file
cp .env.example .env

# Edit .env with your settings
# At minimum, you'll need:
# SECRET_KEY=your-development-secret-key
```

### 5. Run the Development Server

```bash
# From the api directory
cd api
uvicorn app.main:app --reload

# The API will be available at http://localhost:8000
# API documentation at http://localhost:8000/docs
```

## Running Tests

```bash
# Run all tests
pytest

# Run tests with coverage
pytest --cov=app --cov-report=html

# Run a specific test file
pytest tests/unit/test_export_service.py

# Run tests in watch mode
pytest --watch
```

## Code Style Guidelines

This project follows these code style conventions:

### Formatting

- **Black** is used for code formatting
- Run `black .` before committing

### Linting

- **Flake8** is used for linting
- Run `flake8 .` to check for issues

### Type Checking

- **MyPy** is used for type checking
- Run `mypy .` to check types

### Pre-commit Hooks

We recommend setting up pre-commit hooks to run formatting and linting automatically:

```bash
# Install pre-commit
pip install pre-commit

# Install hooks
pre-commit install
```

## Code Organization

```
Discord_Exporter/
├── api/
│   ├── app/
│   │   ├── core/           # Core business logic
│   │   │   └── discord_exporter.py
│   │   ├── infrastructure/  # External services
│   │   │   ├── discord_client.py
│   │   │   └── queue.py
│   │   ├── models/         # Data models
│   │   ├── routes/         # API endpoints
│   │   ├── services/       # Business services
│   │   └── utils/          # Utilities
│   └── tests/              # Test suite
├── Dockerfile
├── docker-compose.yml
└── README.md
```

## Making Changes

### 1. Create a Feature Branch

```bash
# Create and switch to a new branch
git checkout -b feature/your-feature-name
# or
git checkout -b fix/your-bug-fix
```

### 2. Make Your Changes

- Write your code following the project's style guidelines
- Add tests for new functionality
- Update documentation as needed

### 3. Commit Your Changes

We follow conventional commits:

```bash
# Stage your changes
git add .

# Commit with a descriptive message
git commit -m "feat: add new export format support"
```

Types:
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Code style changes (formatting, no logic change)
- `refactor`: Code refactoring
- `test`: Adding or updating tests
- `chore`: Maintenance tasks

### 4. Push to Your Fork

```bash
git push origin feature/your-feature-name
```

### 5. Submit a Pull Request

1. Go to the original repository
2. Click "New Pull Request"
3. Select your fork and branch
4. Fill out the PR template
5. Submit

## PR Guidelines

- **Keep PRs small and focused** - One feature or fix per PR
- **Include tests** - All new code should have test coverage
- **Update documentation** - If you change APIs, update the docs
- **Check code style** - Run `black .`, `flake8 .`, and `mypy .`
- **Describe your changes** - Explain what you changed and why

## Common Development Tasks

### Running a Single Test

```bash
pytest tests/unit/test_export_service.py::test_function_name
```

### Adding a New Export Format

1. Add the format to the schema in `app/models/schemas.py`
2. Implement the export logic in `app/core/discord_exporter.py`
3. Add tests in `tests/`

### Adding a New API Endpoint

1. Define the endpoint in `app/routes/api.py`
2. Add response models if needed in `app/models/schemas.py`
3. Add tests in `tests/integration/`

## Getting Help

- Open an issue for bugs or feature requests
- Join the community discussions
- Check the API documentation at `/docs`

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
