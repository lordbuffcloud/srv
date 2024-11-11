# SRV - Service Manager

A development environment manager for running and managing multiple services.

## Installation

1. Clone the repository:

```bash
git clone https://github.com/lordbuffcloud/srv.git
```

## Prerequisites

### Ngrok Setup
If you plan to use ngrok:
1. Download ngrok from https://ngrok.com/download
2. Extract the executable to a location in your PATH
3. Configure your authtoken:
```bash
ngrok config add-authtoken YOUR_AUTH_TOKEN
```

## Example Configurations

### Ngrok Service
```yaml
services:
  ngrok:
    command: ngrok start --all
    directory: null
    delay: 0
    venv: null
```

</rewritten_file>

