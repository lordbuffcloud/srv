import click
import yaml
import subprocess
import os
from typing import Dict, List
import sys
import signal
import time
import questionary
import pyfiglet
import psutil
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.live import Live
from rich.layout import Layout
from rich.style import Style
from rich import box
from rich.text import Text
from rich.prompt import Confirm

console = Console()

# Custom styles
HEADER_STYLE = Style(color="cyan", bold=True)
SUCCESS_STYLE = Style(color="green", bold=True)
ERROR_STYLE = Style(color="red", bold=True)
INFO_STYLE = Style(color="blue")
WARNING_STYLE = Style(color="yellow")

class AsciiArt:
    @staticmethod
    def get_banner():
        try:
            text_art = pyfiglet.figlet_format("SRV.GLXY", font="cosmic")
            width = max(len(line) for line in text_art.split('\n'))
            stars = "✧ " * (width // 4)
            
            banner = f"""
{stars}
{text_art}
{stars}
            """
            return banner
        except Exception:
            # Fallback if cosmic font is not available
            return pyfiglet.figlet_format("SRV.GLXY")

class Service:
    def __init__(self, name: str, command: str, directory: str = None, delay: int = 0, venv: str = None):
        self.name = name
        self.command = command
        self.directory = os.path.normpath(directory) if directory else None
        self.delay = delay
        self.venv = os.path.normpath(venv) if venv else None
        self.process = None
        self.pid = None
        self.status = "stopped"
        self._find_running_process()

    def _find_running_process(self):
        """Find if this service is already running by checking process names and working directory"""
        try:
            base_command = self.command.split()[0]
            base_name = os.path.basename(base_command)
            expected_dir = os.path.normpath(os.path.expanduser(self.directory)) if self.directory else None

            for proc in psutil.process_iter(['name', 'pid', 'cmdline', 'status', 'cwd']):
                try:
                    # Skip invalid processes
                    if (proc.status() == psutil.STATUS_ZOMBIE or 
                        not proc.is_running()):
                        continue

                    cmdline = proc.cmdline()
                    if not cmdline:
                        continue

                    # Check working directory if specified
                    if expected_dir:
                        try:
                            proc_cwd = os.path.normpath(proc.cwd())
                            if proc_cwd != expected_dir:
                                continue
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            continue

                    # For Python scripts
                    if base_name.endswith('.py'):
                        if ('python' in proc.name().lower() and 
                            any(base_name == os.path.basename(cmd) for cmd in cmdline)):
                            self.pid = proc.pid
                            self.status = "running"
                            return
                    # For executables
                    elif base_name.lower() == proc.name().lower():
                        self.pid = proc.pid
                        self.status = "running"
                        return

                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue
            
            self.pid = None
            self.status = "stopped"

        except Exception as e:
            console.print(f"Error checking process status for {self.name}: {str(e)}", style=ERROR_STYLE)
            self.pid = None
            self.status = "stopped"

    def is_running(self):
        """Check if the service is currently running"""
        if self.pid is None:
            return False
            
        try:
            process = psutil.Process(self.pid)
            
            if not process.is_running() or process.status() == psutil.STATUS_ZOMBIE:
                self.pid = None
                return False

            try:
                cmdline = process.cmdline()
                if not cmdline:
                    self.pid = None
                    return False

                # Verify working directory if specified
                if self.directory:
                    expected_dir = os.path.normpath(os.path.expanduser(self.directory))
                    proc_cwd = os.path.normpath(process.cwd())
                    if proc_cwd != expected_dir:
                        self.pid = None
                        return False

                # Get base command name
                base_command = self.command.split()[0]
                base_name = os.path.basename(base_command)

                # Verify it's the correct process
                if base_name.endswith('.py'):
                    is_correct_process = ('python' in process.name().lower() and 
                                        any(base_name == os.path.basename(cmd) for cmd in cmdline))
                else:
                    is_correct_process = base_name.lower() == process.name().lower()

                if not is_correct_process:
                    self.pid = None
                    return False

                return True

            except (psutil.NoSuchProcess, psutil.AccessDenied):
                self.pid = None
                return False

        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            self.pid = None
            return False
        except Exception as e:
            console.print(f"Error checking running status for {self.name}: {str(e)}", style=ERROR_STYLE)
            self.pid = None
            return False

    def get_status(self):
        if self.is_running():
            self.status = "running"
        else:
            self.status = "stopped"
            self.pid = None
        return self.status

    def get_activation_command(self):
        if not self.venv:
            return None
            
        venv_path = os.path.join(os.path.normpath(os.path.expanduser(self.venv)), 'venv')
        
        if sys.platform == 'win32':
            activate_script = os.path.join(venv_path, 'Scripts', 'activate.ps1')
            return f'& "{activate_script}"'
        else:
            activate_script = os.path.join(venv_path, 'bin', 'activate')
            return f'source "{activate_script}"'

    def is_exe(self):
        return self.command.endswith('.exe') or '/' in self.command or '\\' in self.command

    def get_exe_path(self):
        if self.directory:
            return os.path.normpath(os.path.abspath(os.path.join(os.path.expanduser(self.directory), self.command)))
        return os.path.normpath(os.path.abspath(self.command))

class DevEnvironment:
    def __init__(self):
        # Look for config file in current directory first, then fallback to home directory
        local_config = 'devenv_config.yaml'
        home_config = os.path.expanduser('~/.srv_glxy.yml')
        
        if os.path.exists(local_config):
            self.config_path = local_config
        else:
            self.config_path = home_config
            
        self.services = {}
        self.load_config()

    def show_welcome_screen(self):
        console.print(AsciiArt.get_banner(), style="cyan bold")

    def create_default_config(self):
        default_config = {
            'services': {
                'ngrok': {
                    'command': 'ngrok start --all',
                    'directory': None,
                    'delay': 0,
                    'venv': None
                },
                'file_server': {
                    'command': 'python srv.py',
                    'directory': '~/server',
                    'delay': 2,
                    'venv': '~/venvs/server_env'
                }
            }
        }
        
        try:
            with open(self.config_path, 'w') as f:
                yaml.dump(default_config, f, default_flow_style=False)
            
            console.print(Panel("✨ Created default configuration file", 
                              style="green",
                              box=box.ROUNDED))
        except Exception as e:
            console.print(f"❌ Error creating default configuration: {str(e)}", style=ERROR_STYLE)

    def load_config(self):
        try:
            if not os.path.exists(self.config_path):
                console.print(f"Config file not found at: {self.config_path}", style=WARNING_STYLE)
                self.create_default_config()
                return
            
            console.print(f"Loading config from: {self.config_path}", style=INFO_STYLE)
            
            # Load and parse YAML
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            
            if not config:
                console.print("❌ Empty configuration file", style=ERROR_STYLE)
                return
                
            if 'services' not in config:
                console.print("❌ No 'services' section in configuration", style=ERROR_STYLE)
                return

            console.print(f"Found {len(config['services'])} services in config", style=INFO_STYLE)
            
            self.services = {}
            for name, service_config in config['services'].items():
                try:
                    # Convert paths back to Windows format if needed
                    if service_config.get('directory'):
                        service_config['directory'] = service_config['directory'].replace('/', '\\')
                    if service_config.get('venv'):
                        service_config['venv'] = service_config['venv'].replace('/', '\\')
                    if service_config.get('command'):
                        service_config['command'] = service_config['command'].replace('/', '\\')
                    
                    service_config['name'] = name
                    self.services[name] = Service(**service_config)
                    console.print(f"✓ Loaded service: {name}", style=SUCCESS_STYLE)
                except Exception as e:
                    console.print(f"❌ Error loading service {name}: {str(e)}", style=ERROR_STYLE)
                    console.print(f"Service config: {service_config}", style=ERROR_STYLE)
                    
            console.print(f"Total services loaded: {len(self.services)}", style=INFO_STYLE)
                    
        except Exception as e:
            console.print(f"❌ Error loading configuration: {str(e)}", style=ERROR_STYLE)
            import traceback
            console.print(traceback.format_exc(), style=ERROR_STYLE)

    def start_service(self, service_name: str):
        if service_name not in self.services:
            console.print(f"❌ Service {service_name} not found", style=ERROR_STYLE)
            return False

        service = self.services[service_name]
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            try:
                task = progress.add_task(f"Starting {service_name}...", total=None)
                
                if service.delay > 0:
                    progress.update(task, description=f"Waiting {service.delay}s before starting {service_name}...")
                    time.sleep(service.delay)

                working_dir = None
                if service.directory:
                    working_dir = os.path.normpath(os.path.expanduser(service.directory))
                    if not os.path.exists(working_dir):
                        raise FileNotFoundError(f"Directory not found: {working_dir}")
                    console.print(f"Working directory: {working_dir}", style="blue")
                
                if sys.platform == 'win32':
                    if service.venv:
                        venv_path = os.path.join(os.path.normpath(os.path.expanduser(service.venv)), 'venv')
                        activate_script = os.path.join(venv_path, 'Scripts', 'activate.ps1')
                        
                        if not os.path.exists(activate_script):
                            raise FileNotFoundError(f"Virtual environment activation script not found: {activate_script}")
                        
                        # Create PowerShell script with error handling
                        ps_content = f"""
$ErrorActionPreference = 'Stop'
try {{
    Set-Location "{working_dir}"
    & "{activate_script}"
    {service.command}
}} catch {{
    Write-Host "Error: $_"
    pause
}}
                        """.strip()
                        
                        ps_path = os.path.join(os.getcwd(), f"{service_name}_launcher.ps1")
                        with open(ps_path, 'w') as f:
                            f.write(ps_content)
                        
                        # Start PowerShell with proper arguments
                        process = subprocess.Popen(
                            ["powershell", "-NoExit", "-ExecutionPolicy", "Bypass", "-File", ps_path],
                            cwd=working_dir,
                            creationflags=subprocess.CREATE_NEW_CONSOLE | subprocess.CREATE_NEW_PROCESS_GROUP
                        )
                        
                    elif service.is_exe():
                        exe_path = service.get_exe_path()
                        if not os.path.exists(exe_path):
                            raise FileNotFoundError(f"Executable not found: {exe_path}")
                        
                        process = subprocess.Popen(
                            exe_path,
                            cwd=working_dir or os.path.dirname(exe_path),
                            creationflags=subprocess.CREATE_NEW_CONSOLE | subprocess.CREATE_NEW_PROCESS_GROUP
                        )
                        
                    else:
                        # For non-venv, non-exe commands
                        batch_content = f"""
@echo off
cd /d "{working_dir}"
{service.command}
if errorlevel 1 pause
                        """.strip()
                        
                        batch_path = os.path.join(os.getcwd(), f"{service_name}_launcher.bat")
                        with open(batch_path, 'w') as f:
                            f.write(batch_content)
                        
                        process = subprocess.Popen(
                            batch_path,
                            cwd=working_dir,
                            shell=True,
                            creationflags=subprocess.CREATE_NEW_CONSOLE | subprocess.CREATE_NEW_PROCESS_GROUP
                        )
                    
                    # Store process info and wait to verify it started
                    service.process = process
                    service.pid = process.pid
                    time.sleep(2)  # Wait longer to ensure process starts

                    # Verify process is running
                    if service.is_running():
                        service.status = "running"
                        progress.update(task, description=f"✅ Started {service_name}")
                        return True
                    else:
                        service.status = "stopped"
                        service.pid = None
                        progress.update(task, description=f"❌ Failed to start {service_name}")
                        return False

            except Exception as e:
                console.print(Panel(f"Error starting {service_name}: {str(e)}\nDirectory: {service.directory}\nCommand: {service.command}", 
                                style="red",
                                box=box.ROUNDED))
                service.status = "stopped"
                service.pid = None
                return False

    def list_services(self):
        try:
            table = Table(
                title="🔧 Development Services",
                box=box.ROUNDED,
                header_style="bold magenta",
                border_style="bright_blue"
            )
            
            table.add_column("Service", style="cyan", justify="left")
            table.add_column("Status", style="green", justify="center")
            table.add_column("Command", style="yellow")
            table.add_column("Directory", style="blue")
            table.add_column("VEnv", style="magenta")
            table.add_column("Delay", justify="right", style="magenta")
            
            for name, service in self.services.items():
                status = service.get_status()
                status_style = "green" if status == "running" else "red"
                status_icon = "🟢" if status == "running" else "🔴"
                
                table.add_row(
                    name,
                    Text(f"{status_icon} {status}", style=status_style),
                    service.command,
                    service.directory or "Current Directory",
                    service.venv or "None",
                    str(service.delay) + "s"
                )
            
            console.print(table)
        except Exception as e:
            console.print(f"❌ Error listing services: {str(e)}", style=ERROR_STYLE)

    def add_service_to_config(self, name: str, command: str, directory: str = None, venv: str = None, delay: int = 0):
        """Helper method to safely add a service to the config file"""
        try:
            # Read existing config
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f) or {'services': {}}
            
            if 'services' not in config:
                config['services'] = {}
                
            # Convert Windows paths to use forward slashes
            if directory:
                directory = directory.replace('\\', '/')
            if venv:
                venv = venv.replace('\\', '/')
            if command:
                command = command.replace('\\', '/')
                
            # Add new service
            config['services'][name] = {
                'command': str(command),  # Ensure string type
                'directory': str(directory) if directory else None,
                'venv': str(venv) if venv else None,
                'delay': int(delay)
            }
            
            # Write updated config
            with open(self.config_path, 'w', encoding='utf-8') as f:
                yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
            
            return True
        except Exception as e:
            console.print(f"❌ Error updating config file: {str(e)}", style=ERROR_STYLE)
            return False

    def stop_service(self, service_name: str):
        """Stop a running service"""
        if service_name not in self.services:
            console.print(f"❌ Service {service_name} not found", style=ERROR_STYLE)
            return False

        service = self.services[service_name]
        
        try:
            if not service.is_running():
                console.print(f"Service {service_name} is not running", style=WARNING_STYLE)
                return True

            if sys.platform == 'win32':
                # Try to terminate the process and its children
                parent = psutil.Process(service.pid)
                children = parent.children(recursive=True)
                
                for child in children:
                    try:
                        child.terminate()
                    except psutil.NoSuchProcess:
                        pass
                
                try:
                    parent.terminate()
                except psutil.NoSuchProcess:
                    pass
                
                # Wait for processes to terminate
                gone, alive = psutil.wait_procs([parent] + children, timeout=3)
                
                # Force kill if still alive
                for p in alive:
                    try:
                        p.kill()
                    except psutil.NoSuchProcess:
                        pass
            else:
                # Unix-like systems
                os.kill(service.pid, signal.SIGTERM)
                
            service.pid = None
            service.process = None
            service.status = "stopped"
            
            console.print(f"✅ Stopped {service_name}", style=SUCCESS_STYLE)
            return True
            
        except Exception as e:
            console.print(f"❌ Error stopping {service_name}: {str(e)}", style=ERROR_STYLE)
            return False

def get_service_selection(services: Dict[str, Service], message: str) -> List[str]:
    try:
        choices = [questionary.Choice(name, checked=True) for name in services.keys()]
        return questionary.checkbox(
            message,
            choices=choices,
            style=questionary.Style([
                ('selected', 'bg:blue fg:white'),
                ('checkbox', 'bg:gray fg:white'),
                ('pointer', 'fg:blue bold'),
            ])
        ).ask()
    except Exception as e:
        console.print(f"❌ Error in service selection: {str(e)}", style=ERROR_STYLE)
        return []

@click.group()
def cli():
    """🚀 Development Environment Management CLI"""
    try:
        # Get the command being run
        ctx = click.get_current_context()
        if ctx.invoked_subcommand is None:
            click.echo(ctx.get_help())
    except Exception as e:
        console.print(f"❌ Command error: {str(e)}", style=ERROR_STYLE)

@cli.command()
def interactive():
    """Launch interactive mode"""
    try:
        dev_env = DevEnvironment()
        dev_env.show_welcome_screen()
        
        while True:
            action = questionary.select(
                "What would you like to do?",
                choices=[
                    "Start Services",
                    "Stop Services",
                    "List Services",
                    "Add Service",
                    "Remove Service",
                    "Exit"
                ],
                style=questionary.Style([
                    ('selected', 'bg:blue fg:white'),
                    ('pointer', 'fg:blue bold'),
                ])
            ).ask()
            
            if action == "Start Services":
                selected = get_service_selection(dev_env.services, "Select services to start:")
                if selected:
                    for service in selected:
                        dev_env.start_service(service)
            
            elif action == "Stop Services":
                selected = get_service_selection(dev_env.services, "Select services to stop:")
                if selected:
                    for service in selected:
                        dev_env.stop_service(service)
            
            elif action == "List Services":
                dev_env.list_services()
            
            elif action == "Add Service":
                try:
                    name = questionary.text("Service name:").ask()
                    if not name:
                        continue
                        
                    command = questionary.text("Command to run:").ask()
                    if not command:
                        continue
                        
                    directory = questionary.text("Working directory (optional):").ask()
                    venv = questionary.text("Virtual environment path (optional):").ask()
                    delay = questionary.text("Start delay in seconds:", default="0").ask()
                    
                    if dev_env.add_service_to_config(
                        name=name,
                        command=command,
                        directory=directory if directory else None,
                        venv=venv if venv else None,
                        delay=int(delay)
                    ):
                        console.print(f"✨ Added service: {name}", style=SUCCESS_STYLE)
                        dev_env.load_config()
                    
                except Exception as e:
                    console.print(f"❌ Error adding service: {str(e)}", style=ERROR_STYLE)
            
            elif action == "Remove Service":
                try:
                    selected = get_service_selection(dev_env.services, "Select services to remove:")
                    if selected:
                        if Confirm.ask(f"Are you sure you want to remove the following services: {', '.join(selected)}?"):
                            for service in selected:
                                with open(dev_env.config_path, 'r') as f:
                                    config = yaml.safe_load(f)
                                
                                if service in config['services']:
                                    del config['services'][service]
                                    
                                    with open(dev_env.config_path, 'w') as f:
                                        yaml.dump(config, f, default_flow_style=False)
                                    
                                    console.print(f"✨ Removed service: {service}", style=SUCCESS_STYLE)
                                    dev_env.load_config()
                                else:
                                    console.print(f"Service not found: {service}", style=WARNING_STYLE)
                except Exception as e:
                    console.print(f"❌ Error removing service: {str(e)}", style=ERROR_STYLE)
            
            elif action == "Exit":
                console.print(Panel("👋 Goodbye!", 
                                  style="bold blue",
                                  box=box.ROUNDED))
                break

    except KeyboardInterrupt:
        console.print(Panel("\n👋 Goodbye!", 
                          style="bold blue",
                          box=box.ROUNDED))
    except Exception as e:
        console.print(f"❌ Error in interactive mode: {str(e)}", style=ERROR_STYLE)
@cli.command()
@click.argument('service_names', nargs=-1)
def start(service_names):
    """Start specified services or all if none specified"""
    try:
        dev_env = DevEnvironment()
        
        if not service_names:
            service_names = dev_env.services.keys()
        
        for service in service_names:
            dev_env.start_service(service)
    except Exception as e:
        console.print(f"❌ Error starting services: {str(e)}", style=ERROR_STYLE)

@cli.command()
@click.argument('service_names', nargs=-1)
def stop(service_names):
    """Stop specified services or all if none specified"""
    try:
        dev_env = DevEnvironment()
        
        if not service_names:
            service_names = dev_env.services.keys()
        
        for service in service_names:
            dev_env.stop_service(service)
    except Exception as e:
        console.print(f"❌ Error stopping services: {str(e)}", style=ERROR_STYLE)

@cli.command()
def list():
    """List all configured services"""
    try:
        dev_env = DevEnvironment()
        dev_env.list_services()
    except Exception as e:
        console.print(f"❌ Error listing services: {str(e)}", style=ERROR_STYLE)

@cli.command()
@click.argument('service_names', nargs=-1)
def remove(service_names):
    """Remove specified services from the configuration"""
    try:
        dev_env = DevEnvironment()
        
        if not service_names:
            console.print("No services specified to remove", style=WARNING_STYLE)
            return
        
        for service_name in service_names:
            if Confirm.ask(f"Are you sure you want to remove {service_name}?"):
                with open(dev_env.config_path, 'r') as f:
                    config = yaml.safe_load(f)
                
                if service_name in config['services']:
                    del config['services'][service_name]
                    
                    with open(dev_env.config_path, 'w') as f:
                        yaml.dump(config, f, default_flow_style=False)
                    
                    console.print(f"✨ Removed service: {service_name}", style=SUCCESS_STYLE)
                    dev_env.load_config()
                else:
                    console.print(f"Service not found: {service_name}", style=WARNING_STYLE)
                    
    except Exception as e:
        console.print(f"❌ Error removing services: {str(e)}", style=ERROR_STYLE)

if __name__ == '__main__':
    try:
        cli()
    except KeyboardInterrupt:
        console.print(Panel("\n👋 Goodbye!", 
                          style="bold blue",
                          box=box.ROUNDED))
    except Exception as e:
        console.print(f"❌ Fatal error: {str(e)}", style=ERROR_STYLE)

@cli.command()
def add():
    """Add a new service interactively"""
    try:
        dev_env = DevEnvironment()
        
        name = questionary.text("Service name:").ask()
        if not name:
            return
            
        command = questionary.text("Command to run:").ask()
        if not command:
            return
            
        directory = questionary.text("Working directory (optional):").ask()
        venv = questionary.text("Virtual environment path (optional):").ask()
        delay = questionary.text("Start delay in seconds:", default="0").ask()
        
        if dev_env.add_service_to_config(
            name=name,
            command=command,
            directory=directory if directory else None,
            venv=venv if venv else None,
            delay=int(delay)
        ):
            console.print(f"✨ Added service: {name}", style=SUCCESS_STYLE)
            dev_env.load_config()
            
    except Exception as e:
        console.print(f"❌ Error in add command: {str(e)}", style=ERROR_STYLE)