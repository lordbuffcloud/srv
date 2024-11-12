# Service Galaxy 🌌

Service Galaxy is a powerful service orchestration tool designed to manage and control multiple services in your development environment with ease.

![Service Galaxy Interface](./prrot/srv.png)

## Features 🚀

- **Service Management**: Start, stop, and monitor multiple services from a single interface
- **Interactive Mode**: User-friendly CLI interface for service control
- **Virtual Environment Support**: Automatic venv activation for Python services
- **Process Monitoring**: Real-time status monitoring of all services
- **Flexible Configuration**: YAML-based configuration for easy service setup
- **Multi-Platform**: Supports both Windows and Unix-based systems

## Installation 📦

1. Clone the repository:
```bash
git clone https://github.com/yourusername/service-galaxy.git
cd service-galaxy
```

2. Create and activate a virtual environment:
```bash
python -m venv venv
# Windows
.\venv\Scripts\activate
# Unix
source venv/bin/activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

## Configuration ⚙️

Create a `devenv_config.yaml` file in the root directory:

```yaml
services:
  service_name:
    command: python script.py  # Command to run
    directory: /path/to/dir    # Working directory
    delay: 0                   # Startup delay in seconds
    venv: /path/to/venv       # Virtual environment path (optional)
```

## Usage 💻

### Interactive Mode

```bash
python srv.py interactive
```

This opens an interactive menu with options to:
- List all services
- Start all services
- Start a specific service
- Stop a service
- Exit

### Command Line Interface

Start services:
```bash
python srv.py start [service_name]  # Start specific service
python srv.py start                 # Start all services
```

Stop services:
```bash
python srv.py stop [service_name]   # Stop specific service
python srv.py stop                  # Stop all services
```

List services:
```bash
python srv.py list
```

## Service Types Support 🔧

- **Python Scripts**: Automatic virtual environment activation
- **Node.js/npm**: Handles npm commands and process management
- **Executables**: Supports .exe files and other executables
- **Command-line Tools**: General command-line application support

## Troubleshooting 🔍

- Ensure all paths in `devenv_config.yaml` are correct and accessible
- Check that virtual environments are properly set up for Python services
- Verify that all required dependencies are installed
- Check service logs for specific error messages

## Contributing 🤝

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## License 📄

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments 🙏

- Thanks to all contributors who have helped shape Service Galaxy
- Built with Python and love for the developer community

---

Made with ❤️ by the Service Galaxy Team