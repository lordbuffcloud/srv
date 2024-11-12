import click
import yaml
import subprocess
import os
from typing import Dict, List, Optional, Union
import sys
import signal
import time
import questionary
import pyfiglet
import psutil
from dataclasses import dataclass
from pathlib import Path
import logging
from datetime import datetime
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import threading
from queue import Queue
import asyncio
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.style import Style
from rich.box import ROUNDED
from rich.logging import RichHandler
from rich.prompt import Confirm
import queue  # Add this import statement

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(rich_tracebacks=True)]
)
logger = logging.getLogger("srv.glxy")
console = Console()

STYLES = {
    'header': Style(color="cyan", bold=True),
    'success': Style(color="green", bold=True),
    'error': Style(color="red", bold=True),
    'info': Style(color="blue"),
    'warning': Style(color="yellow"),
    'highlight': Style(color="magenta", bold=True)
}

@dataclass
class ServiceConfig:
    """Service configuration data class"""
    name: str
    command: str
    directory: Optional[str] = None
    delay: int = 0
    venv: Optional[str] = None
    auto_restart: bool = False
    max_retries: int = 3
    retry_delay: int = 5
    env_vars: Optional[Dict[str, str]] = None
    depends_on: Optional[List[str]] = None
    health_check: Optional[str] = None
    health_check_interval: int = 30
    logs_dir: Optional[str] = None

class OutputWindow:
    """Tkinter window for displaying service output"""
    def __init__(self, service_name: str):
        self.root = tk.Tk()
        self.service_name = service_name
        self.setup_ui()
        self.output_queue = Queue()
        self.running = True
        threading.Thread(target=self.process_queue, daemon=True).start()

    def setup_ui(self):
        """Setup the UI components"""
        self.root.title(f"Service Output - {self.service_name}")
        self.root.geometry("800x600")

        # Main frame
        main_frame = ttk.Frame(self.root, padding="5")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Toolbar
        toolbar = ttk.Frame(main_frame)
        toolbar.pack(fill=tk.X, pady=(0, 5))

        ttk.Button(toolbar, text="Clear", command=self.clear_output).pack(side=tk.LEFT, padx=5)
        ttk.Button(toolbar, text="Save", command=self.save_output).pack(side=tk.LEFT, padx=5)

        # Filter
        filter_frame = ttk.Frame(main_frame)
        filter_frame.pack(fill=tk.X, pady=(0, 5))
        ttk.Label(filter_frame, text="Filter:").pack(side=tk.LEFT)
        self.filter_var = tk.StringVar()
        self.filter_var.trace('w', self.apply_filter)
        self.filter_entry = ttk.Entry(filter_frame, textvariable=self.filter_var)
        self.filter_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        # Output area
        self.output_area = scrolledtext.ScrolledText(
            main_frame,
            wrap=tk.WORD,
            background="black",
            foreground="light green",
            font=("Consolas", 10),
        )
        self.output_area.pack(fill=tk.BOTH, expand=True)

        # Configure tags
        self.output_area.tag_configure("stderr", foreground="red")
        self.output_area.tag_configure("stdout", foreground="light green")

        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
    def process_queue(self):
        """Process output queue"""
        while self.running:
            try:
                message = self.output_queue.get(timeout=0.1)
                self.output_area.insert(tk.END, message + '\n')
                self.output_area.see(tk.END)
            except queue.Empty:  # Changed from Queue.Empty to queue.Empty
                continue
            try:
                self.root.update()
            except tk.TclError:
                break

    def add_output(self, text: str, output_type: str = "stdout"):
        """Add output to queue"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.output_queue.put(f"[{timestamp}] {text}")

    def clear_output(self):
        """Clear output area"""
        self.output_area.delete(1.0, tk.END)

    def save_output(self):
        """Save output to file"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{self.service_name}_output_{timestamp}.log"
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(self.output_area.get(1.0, tk.END))
            messagebox.showinfo("Success", f"Output saved to {filename}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save output: {e}")

    def apply_filter(self, *args):
        """Apply filter to output"""
        filter_text = self.filter_var.get().lower()
        self.output_area.delete(1.0, tk.END)
        # Reapply filtered content

    def on_closing(self):
        """Handle window closing"""
        self.running = False
        self.root.destroy()

class Service:
    """Service management class"""
    def __init__(self, config: ServiceConfig):
        self.config = config
        self.name = config.name
        self.process: Optional[subprocess.Popen] = None
        self.pid: Optional[int] = None
        self.status = "stopped"
        self.output_window: Optional[OutputWindow] = None
        self._find_running_process()

    def _find_running_process(self):
        """Find existing process"""
        try:
            base_command = self.config.command.split()[0]
            base_name = os.path.basename(base_command)
            expected_dir = os.path.normpath(os.path.expanduser(self.config.directory)) if self.config.directory else None

            for proc in psutil.process_iter(['name', 'pid', 'cmdline', 'status', 'cwd']):
                if self._is_matching_process(proc, base_name, expected_dir):
                    self.pid = proc.pid
                    self.status = "running"
                    return

            self.pid = None
            self.status = "stopped"

        except Exception as e:
            logger.error(f"Error finding process: {e}")
            self.status = "stopped"

    def _is_matching_process(self, proc, base_name: str, expected_dir: Optional[str]) -> bool:
        """Check if process matches service criteria"""
        try:
            if proc.status() == psutil.STATUS_ZOMBIE:
                return False

            cmdline = proc.cmdline()
            if not cmdline:
                return False

            if base_name.endswith('.py'):
                if 'python' not in proc.name().lower():
                    return False
                if not any(base_name in cmd for cmd in cmdline):
                    return False
            else:
                proc_name = proc.name().lower()
                base_name_lower = base_name.lower()
                if base_name_lower not in proc_name and proc_name not in base_name_lower:
                    return False

            if expected_dir:
                try:
                    proc_cwd = os.path.normpath(proc.cwd())
                    return (proc_cwd.startswith(expected_dir) or expected_dir.startswith(proc_cwd))
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    return False

            return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return False

    def is_running(self):
        """Check if the service is currently running"""
        try:
            base_command = self.config.command.split()[0]
            base_name = os.path.basename(base_command)
            expected_dir = os.path.normpath(os.path.expanduser(self.config.directory)) if self.config.directory else None

            # Check for running processes
            for proc in psutil.process_iter(['name', 'pid', 'cmdline', 'cwd']):
                try:
                    # Skip zombie processes
                    if proc.status() == psutil.STATUS_ZOMBIE:
                        continue

                    cmdline = proc.cmdline()
                    if not cmdline:
                        continue

                    # For Python scripts
                    if base_name.endswith('.py'):
                        if 'python' not in proc.name().lower():
                            continue
                            
                        # Check if our script is in the command line
                        script_found = False
                        for cmd in cmdline:
                            if base_name in cmd:
                                script_found = True
                                break
                        
                        if not script_found:
                            continue

                    # For npm processes
                    elif 'npm' in base_name.lower():
                        if not any('node' in cmd.lower() or 'npm' in cmd.lower() for cmd in cmdline):
                            continue

                    # For ngrok
                    elif 'ngrok' in base_name.lower():
                        if 'ngrok' not in proc.name().lower():
                            continue

                    # For executables
                    else:
                        proc_name = proc.name().lower()
                        base_name_lower = base_name.lower()
                        if base_name_lower not in proc_name and proc_name not in base_name_lower:
                            continue

                    # If directory is specified, verify it
                    if expected_dir:
                        try:
                            proc_cwd = os.path.normpath(proc.cwd())
                            if not (proc_cwd.startswith(expected_dir) or 
                                   expected_dir.startswith(proc_cwd) or
                                   os.path.commonpath([proc_cwd, expected_dir]) == expected_dir):
                                continue
                        except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError):
                            continue

                    # If we get here, we found a matching process
                    self.pid = proc.pid
                    return True

                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            return False

        except Exception as e:
            logger.error(f"Error checking process status: {e}")
            return False

    def start(self) -> bool:
        """Start the service"""
        try:
            if self.is_running():
                logger.warning(f"Service {self.name} is already running")
                return True

            if self.config.delay > 0:
                logger.info(f"Waiting {self.config.delay}s before starting {self.name}")
                time.sleep(self.config.delay)

            # Create output window
            self.output_window = OutputWindow(self.name)

            # Start process
            working_dir = os.path.expanduser(self.config.directory) if self.config.directory else None
            
            if sys.platform == 'win32':
                success = self._start_windows_service(working_dir)
            else:
                success = self._start_unix_service(working_dir)

            return success

        except Exception as e:
            logger.error(f"Error starting service: {e}")
            return False

    def _start_windows_service(self, working_dir: Optional[str]) -> bool:
        """Start service on Windows"""
        try:
            # Create startup info
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            # Build command
            command = self.config.command
            if self.config.venv:
                venv_path = os.path.expanduser(self.config.venv)
                activate_script = os.path.join(venv_path, 'Scripts', 'activate.bat')
                if os.path.exists(activate_script):
                    command = f'cmd /c "{activate_script} && {command}"'

            # Start process
            self.process = subprocess.Popen(
                command,
                cwd=working_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                startupinfo=startupinfo,
                text=True,
                bufsize=1,
                universal_newlines=True,
                shell=True  # Added shell=True for complex commands
            )

            self.pid = self.process.pid
            self.status = "running"

            # Start output readers
            threading.Thread(target=self._read_output, 
                        args=(self.process.stdout, "stdout"), 
                        daemon=True).start()
            threading.Thread(target=self._read_output, 
                        args=(self.process.stderr, "stderr"), 
                        daemon=True).start()

            return True

        except Exception as e:
            logger.error(f"Error in starting service on Windows: {e}")
            return False

    def _start_unix_service(self, working_dir: Optional[str]) -> bool:
        """Start service on Unix"""
        try:
            self.process = subprocess.Popen(
                self.config.command,
                cwd=working_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=True,
                text=True,
                bufsize=1,
                universal_newlines=True
            )

            self.pid = self.process.pid
            self.status = "running"

            # Start output readers
            threading.Thread(target=self._read_output, 
                           args=(self.process.stdout, "stdout"), 
                           daemon=True).start()
            threading.Thread(target=self._read_output, 
                           args=(self.process.stderr, "stderr"), 
                           daemon=True).start()

            return True

        except Exception as e:
            logger.error(f"Error starting Unix service: {e}")
            return False

    def _read_output(self, pipe, output_type: str):
        """Read output from process pipe"""
        try:
            for line in pipe:
                if self.output_window:
                    self.output_window.add_output(line.strip(), output_type)
        except Exception as e:
            logger.error(f"Error reading output: {e}")

    def stop(self) -> bool:
        """Stop the service"""
        try:
            if not self.is_running():
                return True

            if sys.platform == 'win32':
                success = self._stop_windows_service()
            else:
                success = self._stop_unix_service()

            if success:
                self.pid = None
                self.process = None
                self.status = "stopped"
                
                if self.output_window:
                    self.output_window.on_closing()
                    self.output_window = None

            return success

        except Exception as e:
            logger.error(f"Error stopping service: {e}")
            return False

    def _stop_windows_service(self) -> bool:
        """Stop service on Windows"""
        try:
            parent = psutil.Process(self.pid)
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
            
            gone, alive = psutil.wait_procs([parent] + children, timeout=3)
            
            for p in alive:
                try:
                    p.kill()
                except psutil.NoSuchProcess:
                    pass
                    
            return True

        except Exception as e:
            logger.error(f"Error stopping Windows service: {e}")
            return False

    def _stop_unix_service(self) -> bool:
        """Stop service on Unix"""
        try:
            os.kill(self.pid, signal.SIGTERM)
            time.sleep(1)
            if self.is_running():
                os.kill(self.pid, signal.SIGKILL)
            return True
        except ProcessLookupError:
            return True
        except Exception as e:
            logger.error(f"Error stopping Unix service: {e}")
            return False

    def _kill_ngrok_process(self, service: 'Service'):
        """Kill all ngrok processes"""
        try:
            # First try to kill by PID if we have it
            if service.pid:
                try:
                    process = psutil.Process(service.pid)
                    process.kill()
                except psutil.NoSuchProcess:
                    pass

            # Find and kill any ngrok processes
            for proc in psutil.process_iter(['name', 'pid', 'cmdline']):
                try:
                    if 'ngrok' in proc.name().lower():
                        proc.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception as e:
            logger.error(f"Error killing ngrok processes: {e}")

class DevEnvironment:
    """Development environment manager"""
    def __init__(self):
        self.config_path = self._get_config_path()
        self.services: Dict[str, Service] = {}
        self.load_config()

    def _get_config_path(self) -> str:
        """Get configuration file path"""
        local_config = 'devenv_config.yaml'
        home_config = os.path.expanduser('~/.srv_glxy.yml')
        return local_config if os.path.exists(local_config) else home_config

    def show_welcome_screen(self):
        """Show welcome banner"""
        try:
            text_art = pyfiglet.figlet_format("SRV.GLXY", font="cosmic")
            width = max(len(line) for line in text_art.split('\n'))
            stars = "✧ " * (width // 4)
            banner = f"\n{stars}\n{text_art}\n{stars}"
            console.print(banner, style="cyan bold")
        except Exception:
            console.print(pyfiglet.figlet_format("SRV.GLXY"), style="cyan bold")

    def create_default_config(self):
        """Create default configuration file"""
        default_config = {
            'services': {
                'example': {
                    'command': 'python script.py',
                    'directory': '~/projects/example',
                    'delay': 0,
                    'venv': '~/venvs/example',
                    'auto_restart': False,
                    'max_retries': 3,
                    'retry_delay': 5,
                    'health_check': None,
                    'health_check_interval': 30,
                    'logs_dir': '~/logs'
                }
            }
        }
        
        try:
            with open(self.config_path, 'w') as f:
                yaml.dump(default_config, f, default_flow_style=False)
            console.print("✨ Created default configuration file", style=STYLES['success'])
        except Exception as e:
            console.print(f"❌ Error creating default configuration: {e}", style=STYLES['error'])

    def load_config(self):
        """Load configuration from file"""
        try:
            if not os.path.exists(self.config_path):
                console.print(f"Config file not found at: {self.config_path}", style=STYLES['warning'])
                self.create_default_config()
                return
            
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            
            if not config or 'services' not in config:
                console.print("❌ Invalid configuration file", style=STYLES['error'])
                return

            self.services = {}
            for name, service_config in config['services'].items():
                try:
                    service_config['name'] = name
                    self.services[name] = Service(ServiceConfig(**service_config))
                    console.print(f"✓ Loaded service: {name}", style=STYLES['success'])
                except Exception as e:
                    console.print(f"❌ Error loading service {name}: {e}", style=STYLES['error'])
                    
        except Exception as e:
            console.print(f"❌ Error loading configuration: {e}", style=STYLES['error'])

    def add_service_to_config(self, **service_config) -> bool:
        """Add a new service to configuration"""
        try:
            with open(self.config_path, 'r') as f:
                config = yaml.safe_load(f) or {'services': {}}
            
            if 'services' not in config:
                config['services'] = {}
            
            name = service_config.pop('name')
            config['services'][name] = service_config
            
            with open(self.config_path, 'w') as f:
                yaml.dump(config, f, default_flow_style=False)
            
            return True
            
        except Exception as e:
            console.print(f"❌ Error updating config file: {e}", style=STYLES['error'])
            return False

    def remove_service(self, service_name: str) -> bool:
        """Remove a service from configuration"""
        try:
            with open(self.config_path, 'r') as f:
                config = yaml.safe_load(f)
            
            if service_name in config['services']:
                service = self.services.get(service_name)
                if service and service.is_running():
                    service.stop()
                
                del config['services'][service_name]
                del self.services[service_name]
                
                with open(self.config_path, 'w') as f:
                    yaml.dump(config, f, default_flow_style=False)
                
                console.print(f"✨ Removed service: {service_name}", style=STYLES['success'])
                return True
            
            return False
            
        except Exception as e:
            console.print(f"❌ Error removing service: {e}", style=STYLES['error'])
            return False

    def start_service(self, service_name: str):
        if service_name not in self.services:
            console.print(f"❌ Service {service_name} not found", style=STYLES['error'])
            return False

        service = self.services[service_name]
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            try:
                task = progress.add_task(f"Starting {service_name}...", total=None)
                
                if service.config.delay > 0:
                    progress.update(task, description=f"Waiting {service.config.delay}s before starting {service_name}...")
                    time.sleep(service.config.delay)

                working_dir = None
                if service.config.directory:
                    working_dir = os.path.normpath(os.path.expanduser(service.config.directory))
                    if not os.path.exists(working_dir):
                        raise FileNotFoundError(f"Directory not found: {working_dir}")
                    console.print(f"Working directory: {working_dir}", style="blue")

                # Prepare the command based on the service type
                if 'npm' in service.config.command:
                    # For npm services
                    command = f'start cmd.exe /K "cd /d {working_dir} && {service.config.command}"'
                elif service.config.command.endswith('.exe'):
                    # For executable files
                    command = f'start "" "{service.config.command}"'
                elif 'python' in service.config.command:
                    # For Python scripts with venv support
                    if service.config.venv:
                        venv_path = os.path.expanduser(service.config.venv)
                        activate_cmd = f"call {venv_path}\\Scripts\\activate.bat"
                        command = f'start cmd.exe /K "{activate_cmd} && cd /d {working_dir} && {service.config.command}"'
                    else:
                        command = f'start cmd.exe /K "cd /d {working_dir} && {service.config.command}"'
                else:
                    # For other commands
                    command = f'start cmd.exe /K "cd /d {working_dir} && {service.config.command}"'

                console.print(f"Executing command: {command}", style="yellow")

                # Start the process
                if sys.platform == 'win32':
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    
                    process = subprocess.Popen(
                        command,
                        shell=True,
                        startupinfo=startupinfo,
                        creationflags=subprocess.CREATE_NEW_CONSOLE
                    )
                else:
                    process = subprocess.Popen(
                        command,
                        shell=True,
                        preexec_fn=os.setsid
                    )

                # Store process info
                service.process = process
                service.pid = process.pid
                
                # Wait a bit to let the process start
                time.sleep(3)

                # Check if process is running
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
                console.print(Panel(f"Error starting {service_name}: {str(e)}\nDirectory: {service.config.directory}\nCommand: {service.config.command}", 
                                style="red",
                                box=box.ROUNDED))
                service.status = "stopped"
                service.pid = None
                return False

    def stop_service(self, service_name: str) -> bool:
        """Stop a service"""
        if service_name not in self.services:
            console.print(f"❌ Service {service_name} not found", style=STYLES['error'])
            return False

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task(f"Stopping {service_name}...", total=None)
            
            service = self.services[service_name]
            
            # Force kill based on service type
            if 'npm' in service.config.command:
                self._kill_npm_processes(service)
            elif 'python' in service.config.command:
                self._kill_python_processes(service)
            elif 'ngrok' in service.config.command:  # Added ngrok handling
                self._kill_ngrok_process(service)
            else:
                success = service.stop()
            
            # Verify the service is actually stopped
            time.sleep(1)  # Give time for processes to clean up
            if not service.is_running():
                progress.update(task, description=f"✅ Stopped {service_name}")
                success = True
            else:
                progress.update(task, description=f"❌ Failed to stop {service_name}")
                success = False
            
            return success

    def _kill_npm_processes(self, service: Service):
        """Kill all related npm/node processes"""
        try:
            if service.pid:
                # Kill the main process and its children
                process = psutil.Process(service.pid)
                children = process.children(recursive=True)
                
                # Kill children first
                for child in children:
                    try:
                        child.kill()
                    except psutil.NoSuchProcess:
                        pass
                
                # Kill main process
                try:
                    process.kill()
                except psutil.NoSuchProcess:
                    pass
                
            # Kill any remaining node processes in the service directory
            for proc in psutil.process_iter(['name', 'pid', 'cmdline', 'cwd']):
                try:
                    if (proc.name().lower() in ['node.exe', 'npm.cmd'] and 
                        service.config.directory and 
                        os.path.normpath(proc.cwd()).startswith(
                            os.path.normpath(os.path.expanduser(service.config.directory))
                        )):
                        proc.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception as e:
            logger.error(f"Error killing npm processes: {e}")

    def _kill_python_processes(self, service: Service):
        """Kill all related Python processes"""
        try:
            if service.pid:
                process = psutil.Process(service.pid)
                children = process.children(recursive=True)
                
                # Kill children first
                for child in children:
                    try:
                        child.kill()
                    except psutil.NoSuchProcess:
                        pass
                
                # Kill main process
                try:
                    process.kill()
                except psutil.NoSuchProcess:
                    pass
                
            # Kill any matching Python processes
            script_name = os.path.basename(service.config.command)
            for proc in psutil.process_iter(['name', 'pid', 'cmdline', 'cwd']):
                try:
                    if (proc.name().lower() == 'python.exe' and 
                        service.config.directory and 
                        os.path.normpath(proc.cwd()).startswith(
                            os.path.normpath(os.path.expanduser(service.config.directory))
                        ) and
                        any(script_name in cmd for cmd in proc.cmdline())):
                        proc.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception as e:
            logger.error(f"Error killing Python processes: {e}")

    def list_services(self):
        """List all services and their status"""
        table = Table(
            title="🔧 Development Services",
            box=ROUNDED,
            header_style="bold magenta",
            border_style="bright_blue"
        )
        
        table.add_column("Service", style="cyan", justify="left")
        table.add_column("Status", style="green", justify="center")
        table.add_column("Command", style="yellow")
        table.add_column("Directory", style="blue")
        table.add_column("VEnv", style="magenta")
        
        for name, service in self.services.items():
            status = "🟢 running" if service.is_running() else "🔴 stopped"
            status_style = "green" if service.is_running() else "red"
            
            table.add_row(
                name,
                status,
                service.config.command,
                service.config.directory or "Current Directory",
                service.config.venv or "None"
            )
        
        console.print(table)
@click.group()
def cli():
    """🚀 Development Environment Management CLI"""
    try:
        ctx = click.get_current_context()
        if ctx.invoked_subcommand is None:
            click.echo(ctx.get_help())
    except Exception as e:
        console.print(f"❌ Command error: {e}", style=STYLES['error'])

@cli.command()
def interactive():
    """Launch interactive mode"""
    try:
        console.print("Entering interactive mode...", style="bold green")
        dev_env = DevEnvironment()
        dev_env.show_welcome_screen()
        
        # Example of interactive loop
        while True:
            action = questionary.select(
                "Choose an action:",
                choices=[
                    "List services",
                    "Start all services",
                    "Start a service",
                    "Stop a service",
                    "Exit"
                ]
            ).ask()

            if action == "List services":
                dev_env.list_services()
            elif action == "Start all services":
                console.print("\n🚀 Starting all services...", style="bold green")
                for service_name in dev_env.services.keys():
                    dev_env.start_service(service_name)
                console.print("\n✨ Finished starting all services", style="bold green")
            elif action == "Start a service":
                service_name = questionary.text("Enter the service name to start:").ask()
                dev_env.start_service(service_name)
            elif action == "Stop a service":
                service_name = questionary.text("Enter the service name to stop:").ask()
                dev_env.stop_service(service_name)
            elif action == "Exit":
                console.print("Exiting interactive mode...", style="bold red")
                break

    except Exception as e:
        console.print(f"❌ Error in interactive mode: {e}", style=STYLES['error'])

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
        console.print(f"❌ Error starting services: {e}", style=STYLES['error'])

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
        console.print(f"❌ Error stopping services: {e}", style=STYLES['error'])

@cli.command()
def list():
    """List all configured services"""
    try:
        dev_env = DevEnvironment()
        dev_env.list_services()
    except Exception as e:
        console.print(f"❌ Error listing services: {e}", style=STYLES['error'])


if __name__ == '__main__':
    try:
        cli()
    except KeyboardInterrupt:
        console.print("\n👋 Goodbye!", style="bold blue")
    except Exception as e:
        console.print(f"❌ Fatal error: {e}", style=STYLES['error'])