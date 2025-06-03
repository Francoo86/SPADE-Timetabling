from datetime import datetime
from enum import Enum
import sys
import os

class LogLevel(Enum):
    DEBUG = 10
    INFO = 20
    WARNING = 30
    ERROR = 40
    CRITICAL = 50
    
NO_DISPLAY = True

class AgentLogger:
    def __init__(self, agent_name: str, min_level: LogLevel = LogLevel.INFO):
        self.agent_name = agent_name
        self.min_level = min_level
        self.log_file = None
        
        # Create logs directory if it doesn't exist
        if not os.path.exists('logs'):
            os.makedirs('logs')
            
        # Create or open log file
        # self.log_file = open(f'logs/{agent_name}.log', 'a')
        self.log_file = None

    def _log(self, level: LogLevel, message: str, *args, **kwargs):
        if level.value < self.min_level.value:
            return
            
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        formatted_message = message.format(*args, **kwargs) if args or kwargs else message
        log_entry = f"[{timestamp}] {self.agent_name} {level.name}: {formatted_message}"
        
        # Write to file
        if self.log_file:
            self.log_file.write(log_entry + '\n')
            self.log_file.flush()
        
        # Print to console
        print(log_entry)

    def debug(self, message: str, *args, **kwargs):
        self._log(LogLevel.DEBUG, message, *args, **kwargs)

    def info(self, message: str, *args, **kwargs):
        self._log(LogLevel.INFO, message, *args, **kwargs)

    def warning(self, message: str, *args, **kwargs):
        self._log(LogLevel.WARNING, message, *args, **kwargs)

    def error(self, message: str, *args, **kwargs):
        self._log(LogLevel.ERROR, message, *args, **kwargs)

    def critical(self, message: str, *args, **kwargs):
        self._log(LogLevel.CRITICAL, message, *args, **kwargs)

    def set_level(self, level: LogLevel):
        """Change the minimum log level."""
        self.min_level = level

    def close(self):
        """Close the log file."""
        if self.log_file:
            self.log_file.close()
            self.log_file = None

    def __del__(self):
        """Ensure log file is closed when logger is deleted."""
        self.close()